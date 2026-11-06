// kalmido-suite:
// 2.521.0 UI test (#4476 the reading view of the documents, includes #4399 the width of the pane), own container (start.sh),
// jsdom + Firefox (1280 px, 2900 px, phone 390 px). Invented data only. P2521C_NOSTART=1 = the container runs.
// - computer: the button "Read" in the bar opens the first document in the reading view (list = narrow column, the preview
//   a scrollable box with every page and zoom buttons, the properties folded away with one button); on / off and the folded
//   properties are kept per device (localStorage), a new start keeps the view
// - the arrow keys up / down leaf in the reading view and in "To review", also after the open one left the list (checked)
// - the full screen "Show": two buttons and the arrow keys left / right leaf to the previous / next document without closing it;
//   the pane follows
// - #4399: a grip between list and pane (outside the reading view, too) sets the width, kept per device, double click = standard
// - phone 390 px: no "Read", no grip; the document opens as its own page as before, also with the reading view kept
// - Firefox 1280 / 2900: the list column is narrow, the pane takes the rest (no centred width), the preview fills the height and
//   draws both pages of a PDF; 2900: the properties stand beside the preview, 1280: below it; the grip drags the width
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2521_c_docread_ui', check, shots: 'P2521C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2521C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
// 2.582.0 (#4830): the shared wait of tests/boot.js by time (at least 15 s), not 60 rounds - under a loaded Mac the new start took longer
const until = (fn, n = 60) => require('./boot').until(fn, {timeout: Math.max(15000, n * 200), step: 200});
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

function pdf(pages) {  // a PDF with one text page per entry, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c), n = pages.length;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + 2 * i} 0 R`).join(' ')}] /Count ${n} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  pages.forEach((lines, i) => {
    const st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ${5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>`,
      `<< /Length ${st.length} >>\nstream\n${st}\nendstream`);
  });
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, pages) {
  const fd = new FormData();
  fd.append('files', new Blob([pdf(pages)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
const WIDE = {'(min-width:64rem)': true};  // jsdom: a computer window wide enough for the reading view

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const IDS = [];
  for (const [n, l] of [['one.pdf', 'Versicherung Beispiel AG'], ['two.pdf', 'Stadtwerke Musterstadt'], ['three.pdf', 'Telefon Beispiel GmbH'], ['four.pdf', 'Verein Beispielhausen']])
    IDS.push(await upload(n, [[l, 'Brief', 'Datum 0' + (IDS.length + 1) + '.10.2026'], ['Seite zwei', l]]));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});

  // ================= computer (jsdom): the button, the view, kept per device
  const shared = {store: {}, wins: []};
  const w = await boot({user: 'alice', hash: 'docs', media: WIDE, shared}), d = w.document;
  await until(() => d.querySelectorAll('.dc-card').length === 4);
  const order = w.eval('DC.docs.map(x => x.id)');
  const paneId = () => +(d.querySelector('.dc-pane .dc-body')?.dataset.id || 0);
  const rb = () => d.querySelector('.dc-view .dc-bar [data-dc="read"]');
  check(rb() && rb().getAttribute('aria-pressed') === 'false' && /Read/.test(rb().textContent), 'computer: the button "Read" in the bar of the list');
  click(w, rb());
  check(await until(() => paneId() === order[0] && d.querySelector('.dc-wrap.dc-paneon.dc-read')), 'Read opens the first document in the reading view');
  check(w.eval(`localStorage.getItem('tasks.dc.read')`) === 'true' && rb()?.getAttribute('aria-pressed') === 'true', '... kept on this device, the button pressed');
  check(d.querySelector('.dc-pane .dc-rv') && !d.querySelector('.dc-pane button.dc-prev') && d.querySelector('.dc-pane .dc-rvbar [data-dc="rz:in"]'), '... the preview is a scrollable box with zoom buttons');
  check(d.querySelector('.dc-pane .dc-main.dc-rd > .dc-top') && d.querySelector('.dc-pane .dc-main.dc-rd > .dc-props #dc-sender'), '... the preview and the properties in two parts');
  check(d.querySelector('.dc-wrap > [data-dcgrip="list"]') && !d.querySelector('.dc-wrap > [data-dcgrip="pane"]'), '... a grip for the width of the list column');
  // zoom
  click(w, d.querySelector('.dc-pane [data-dc="rz:in"]'));
  check(await until(() => d.querySelector('.dc-pane .dc-rzp')?.textContent.trim() === '125 %'), 'zoom in: 125 %');
  click(w, d.querySelector('.dc-pane [data-dc="rz:fit"]'));
  check(await until(() => d.querySelector('.dc-pane .dc-rzp')?.textContent.trim() === '100 %'), '... fit to width: 100 %');
  // the properties folded away, kept
  const pb = () => d.querySelector('.dc-pane [data-dc="rprops"]');
  check(pb()?.getAttribute('aria-expanded') === 'true', 'the button to fold the properties');
  click(w, pb());
  check(await until(() => d.querySelector('.dc-pane .dc-main.dc-pcol') && pb()?.getAttribute('aria-expanded') === 'false'), '... folds them away');
  check(w.eval(`localStorage.getItem('tasks.dc.readProps')`) === 'true', '... kept on this device');

  // the arrow keys leaf, the card follows
  d.activeElement?.blur?.();
  keyOn(w, d.body, 'ArrowDown');
  check(await until(() => paneId() === order[1] && d.querySelector(`.dc-card[data-k="dc${order[1]}"]`)?.classList.contains('dc-cur')), 'arrow down in the reading view: the next document, its card marked');
  check(d.querySelector('.dc-wrap.dc-read') && d.querySelector('.dc-pane .dc-rv') && d.querySelector('.dc-pane .dc-main.dc-pcol'), '... still the reading view, the properties still folded');
  keyOn(w, d.body, 'ArrowUp');
  check(await until(() => paneId() === order[0]), 'arrow up: the one before');

  // the full screen leafs without closing
  click(w, d.querySelector('.dc-pane .dc-acts [data-dc="view"]'));
  const lb = () => d.querySelector('.lightbox.pview');
  check(await until(() => lb()?.querySelector('.pvdocs [data-pv="dnext"]')), 'Show: the full screen with the buttons previous / next document');
  check(/1 of 4/.test(lb()?.querySelector('.pvdno')?.textContent || '') && lb().querySelector('[data-pv="dprev"]').disabled, '... "1 of 4", the first has no previous one');
  keyOn(w, lb(), 'ArrowRight');
  check(await until(() => paneId() === order[1] && /2 of 4/.test(lb()?.querySelector('.pvdno')?.textContent || '')), 'arrow right in the full screen: the next document, the pane follows, the full screen stays');
  click(w, lb().querySelector('[data-pv="dnext"]'));
  check(await until(() => paneId() === order[2] && /3 of 4/.test(lb()?.querySelector('.pvdno')?.textContent || '')), '... the button next document as well');
  keyOn(w, lb(), 'ArrowLeft');
  check(await until(() => paneId() === order[1] && /2 of 4/.test(lb()?.querySelector('.pvdno')?.textContent || '')), '... arrow left: the one before');
  check(d.querySelectorAll('.lightbox').length === 1, '... one full screen, not one per document');
  keyOn(w, lb(), 'Escape');
  check(await until(() => !lb() && paneId() === order[1]), 'Esc closes the full screen, the pane stays on the document');

  // a new start keeps the view (same device)
  w.close();
  const w2 = await boot({user: 'alice', hash: `docs/${order[2]}`, media: WIDE, shared}), d2 = w2.document;
  check(await until(() => +(d2.querySelector('.dc-pane .dc-body')?.dataset.id || 0) === order[2] && d2.querySelector('.dc-wrap.dc-read .dc-pane .dc-rv') && d2.querySelector('.dc-pane .dc-main.dc-pcol'), 150), 'a new start: the reading view and the folded properties kept');  // 2.582.0 (#4830): a cold boot, up to 30 s
  click(w2, d2.querySelector('.dc-pane [data-dc="rprops"]'));
  await until(() => !d2.querySelector('.dc-pane .dc-main.dc-pcol'));
  // off again: the pane as before, with the grip of its width (#4399)
  click(w2, d2.querySelector('.dc-view [data-dc="read"]'));
  check(await until(() => !d2.querySelector('.dc-wrap.dc-read') && d2.querySelector('.dc-pane button.dc-prev') && !d2.querySelector('.dc-pane .dc-rv')), 'Read off: the pane as before (preview on top)');
  check(w2.eval(`localStorage.getItem('tasks.dc.read')`) === null, '... kept off');
  const g = d2.querySelector('.dc-wrap > [data-dcgrip="pane"]');
  check(g && /Resize/.test(g.getAttribute('aria-label') || ''), '#4399: a grip for the width of the pane beside the list');
  w2.eval(`localStorage.setItem('tasks.dc.paneW', '500'); dc_draw()`);
  check(await until(() => /--dc-pw:\s*500px/.test(d2.querySelector('.dc-wrap')?.getAttribute('style') || '')), '... a kept width is drawn on the frame');
  g.focus(); keyOn(w2, d2.querySelector('[data-dcgrip="pane"]'), 'Home');
  check(await until(() => w2.eval(`localStorage.getItem('tasks.dc.paneW')`) === null && !/--dc-pw/.test(d2.querySelector('.dc-wrap')?.getAttribute('style') || '')), '... Home (like a double click) = the standard width again');
  w2.close();

  // ================= "To review": the arrow keys leaf on, also after the open one was checked
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: false});
  const w3 = await boot({user: 'alice', hash: 'docs/review', media: WIDE, ls: {'tasks.dc.read': 'true'}}), d3 = w3.document;
  await until(() => d3.querySelectorAll('.dc-card').length === 4 && w3.eval('DC.f.review'));
  const ro = w3.eval('DC.docs.map(x => x.id)');
  click(w3, d3.querySelector(`.dc-view [data-dco="${ro[1]}"]`));
  const p3 = () => +(d3.querySelector('.dc-pane .dc-body')?.dataset.id || 0);
  check(await until(() => p3() === ro[1] && d3.querySelector('.dc-wrap.dc-read')), 'To review: the document opens in the reading view');
  d3.activeElement?.blur?.();
  keyOn(w3, d3.body, 'ArrowDown');
  check(await until(() => p3() === ro[2]), 'To review: arrow down = the next one');
  // checked elsewhere (another device): the list loads without it, the arrow keys go on from where it stood
  await call('POST', `/api/docs/${ro[2]}/review`, {done: true});
  w3.eval('dc_load()');
  check(await until(() => d3.querySelectorAll('.dc-card').length === 3 && p3() === ro[2]), '... checked: it left the list, the pane still shows it');
  keyOn(w3, d3.body, 'ArrowDown');
  check(await until(() => p3() === ro[3]), '... arrow down goes on with the one after it (not stuck)');
  keyOn(w3, d3.body, 'ArrowUp');
  check(await until(() => p3() === ro[1]), '... arrow up the one before');
  w3.close();
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});

  // ================= phone: as before
  const m = await boot({user: 'alice', hash: 'docs', mobile: true, ls: {'tasks.dc.read': 'true'}}), dm = m.document;
  await until(() => dm.querySelectorAll('.dc-card').length === 4);
  check(!dm.querySelector('[data-dc="read"]') && !dm.querySelector('[data-dcgrip]'), 'phone: no "Read", no grip');
  click(m, dm.querySelector(`[data-dco="${order[0]}"]`));
  check(await until(() => dm.querySelector('.modal.dc-md #dc-sender') && dm.querySelector('.modal.dc-md button.dc-prev') && !dm.querySelector('.dc-rv') && !dm.querySelector('.dc-read')), 'phone: the document opens as its own page as before (the reading view kept on the device changes nothing)');
  m.close();

  // ================= Firefox: the real layout
  await firefox(async ({cmd, ev, nav, ctx, shot, idle}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    const R = sel => `(() => { const e = document.querySelector('${sel}'); if (!e) return null; const r = e.getBoundingClientRect(); return {l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom), w: Math.round(r.width), h: Math.round(r.height)}; })()`;
    for (const [W, Hh] of [[1280, 860], [2900, 1400]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + (W === 1280 ? '#docs' : `#docs/${order[0]}`));
      check(await wait(`document.querySelectorAll('.dc-card').length === 4`), `Firefox ${W}: four cards`);
      if (W === 1280) {
        await ev(`(document.querySelector('.dc-view [data-dc="read"]').click(), 1)`);
      }
      check(await wait(`!!document.querySelector('.dc-wrap.dc-read .dc-pane .dc-rv')`), `Firefox ${W}: the reading view` + (W > 1280 ? ' (kept from before)' : ''));
      check(await wait(`document.querySelectorAll('.dc-pane .dc-rv .dc-rpg canvas').length >= 1`, 80), `Firefox ${W}: the first page drawn`);
      const v = await ev(R('#view')), wr = await ev(R('.dc-wrap')), lst = await ev(R('.dc-wrap > .dc-view')), pn = await ev(R('.dc-pane')), rv = await ev(R('.dc-pane .dc-rv')), pr = await ev(R('.dc-pane .dc-props'));
      const info = JSON.stringify({v, wr, lst, pn, rv, pr});
      check(v && wr && wr.l - v.l < 40 && v.r - wr.r < 40, `Firefox ${W}: the view is not centred, no empty strip ` + info);
      check(lst && pn && lst.w < 420 && lst.w >= 200 && pn.l > lst.r && pn.w > W * 0.4, `Firefox ${W}: the list a narrow column, the pane takes the rest ` + info);
      check(rv && rv.h > Hh * 0.5, `Firefox ${W}: the preview fills the height ` + info);
      if (W === 2900) check(pr && pr.l >= rv.r && pr.w > 250, 'Firefox 2900: the properties beside the preview ' + info);
      else check(pr && pr.t >= rv.b - 2, 'Firefox 1280: the properties below the preview ' + info);
      // both pages, scrolled into view
      await ev(`(() => { const b = document.querySelector('.dc-pane .dc-rv'); b.scrollTop = b.scrollHeight; return 1; })()`);
      check(await wait(`document.querySelectorAll('.dc-pane .dc-rv .dc-rpg').length === 2 && document.querySelectorAll('.dc-pane .dc-rv .dc-rpg canvas').length === 2`, 80), `Firefox ${W}: both pages of the PDF drawn (scrolled)`);
      const c0 = await ev(R('.dc-pane .dc-rv .dc-rpg'));
      await ev(`(document.querySelector('.dc-pane [data-dc="rz:in"]').click(), 1)`);
      check(await wait(`document.querySelector('.dc-pane .dc-rv .dc-rpg').getBoundingClientRect().width > ${c0.w * 1.2}`), `Firefox ${W}: zoom in makes the page bigger`);
      await ev(`(document.querySelector('.dc-pane [data-dc="rz:fit"]').click(), 1)`);
      await shot(`p2521c-read-${W}.png`);
    }
    // the grip drags the list column wider; kept after a reload
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + '#docs');
    check(await wait(`document.querySelectorAll('.dc-card').length === 4`), 'Firefox: the list again');
    await ev(`(document.querySelector('.dc-view [data-dco="${order[0]}"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.dc-wrap.dc-read [data-dcgrip="list"]') && document.querySelector('.dc-pane .dc-body')?.dataset.id === '${order[0]}' && !!document.querySelector('.dc-pane .dc-rv canvas')`, 80), 'Firefox: the grip of the list column');
    await idle();  // the list and the pane drawn (a redraw while dragging takes the kept width, measured below once it settled)
    const w0 = (await ev(R('.dc-wrap > .dc-view'))).w;
    await ev(`(() => { const g = document.querySelector('[data-dcgrip="list"]'), r = g.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 40;
      g.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, button: 0, clientX: x, clientY: y, pointerId: 77}));
      document.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, clientX: x + 50, clientY: y, pointerId: 77}));
      document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, clientX: x + 50, clientY: y, pointerId: 77})); return 1; })()`);
    await wait(`Math.abs(document.querySelector('.dc-wrap > .dc-view').getBoundingClientRect().width - ${w0 + 50}) <= 3`, 20);
    const w1 = (await ev(R('.dc-wrap > .dc-view'))).w;
    check(Math.abs(w1 - w0 - 50) <= 3, `Firefox: dragging the grip widens the list column ${w0} -> ${w1} (kept: ${await ev("localStorage.getItem('tasks.dc.readW')")})`);
    check(Math.abs(+(await ev(`localStorage.getItem('tasks.dc.readW')`)) - w1) <= 1, 'Firefox: the width kept on this device');
    await nav(B + `#docs/${order[0]}`);
    check(await wait(`!!document.querySelector('.dc-wrap.dc-read .dc-pane .dc-rv') && Math.abs(document.querySelector('.dc-wrap > .dc-view').getBoundingClientRect().width - ${w1}) <= 2`), 'Firefox: after a reload the same width');
    // far to the right: the pane keeps its room (30rem); the list stops there
    const far = `(() => { const g = document.querySelector('[data-dcgrip="list"]'), r = g.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + 40;
      g.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, button: 0, clientX: x, clientY: y, pointerId: 77}));
      document.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, clientX: x + DX, clientY: y, pointerId: 77}));
      document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, clientX: x + DX, clientY: y, pointerId: 77})); return 1; })()`;
    await ev(far.replace(/DX/g, '2000'));
    const pf = await ev(R('.dc-pane'));
    check(pf && pf.w >= 470, 'Firefox: dragged far, the pane keeps at least 30rem ' + JSON.stringify(pf));
    // the full screen leafs, the pane follows
    await ev(`(document.querySelector('.dc-pane .dc-acts [data-dc="view"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.lightbox.pview .pvpage canvas')`, 80), 'Firefox: Show opens the full screen');
    await ev(`(document.querySelector('.lightbox.pview').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true})), 1)`);
    check(await wait(`document.querySelector('.dc-pane .dc-body')?.dataset.id === '${order[1]}' && /2 of 4/.test(document.querySelector('.lightbox.pview .pvdno')?.textContent || '') && !!document.querySelector('.lightbox.pview .pvpage canvas')`, 80), 'Firefox: arrow right shows the next document in the full screen');
    await shot('p2521c-full.png');
    await ev(`(document.querySelector('.lightbox.pview [data-pv="x"]').click(), 1)`);
    // phone: as before, the kept reading view changes nothing
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#docs');
    check(await wait(`document.querySelectorAll('.dc-card').length === 4`), 'Firefox phone: the cards');
    check(!(await ev(`!!document.querySelector('[data-dc="read"]') || !!document.querySelector('[data-dcgrip]')`)), 'Firefox phone: no Read, no grip');
    await ev(`(document.querySelector('.dc-view [data-dco="${order[0]}"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.modal.dc-md #dc-sender') && !document.querySelector('.dc-rv')`), 'Firefox phone: the document opens as its own page');
    const p = await ev(`(() => { const c = document.querySelector('.modal.dc-md > .card').getBoundingClientRect(); return {w: Math.round(c.width), sw: document.querySelector('.modal.dc-md > .card').scrollWidth, cw: document.querySelector('.modal.dc-md > .card').clientWidth}; })()`);
    check(p && p.w >= 388 && p.sw <= p.cw + 1, 'Firefox phone: a whole page, no sideways scrolling ' + JSON.stringify(p));
  }, false);

  console.log(`p2521_c_docread_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
