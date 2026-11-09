// kalmido-suite:
// 2.430.0 UI test (#3582: a click on a document opens it in a pane beside the list, like a list's task panel), own
// container (start.sh), jsdom + Firefox (1280 px, phone 390 px). Invented data only. P2430_NOSTART=1 = the container runs.
// - computer: a click on a card opens the pane right of the list (no dialog), the card is marked, the hash is #docs/<id>;
//   the preview on top, the fields below; a field changed in the pane saves at once
// - a click on another card / the arrow keys down and up switch the pane; Esc closes it (#docs again)
// - a plain click always opens, also while choosing; choosing = the box on the card, Ctrl/Cmd-click (nothing opens)
// - phone: the document opens as a whole page with a Back arrow; Back leads to the list
// - Firefox: the pane stands right of the list, the list stays visible; a PDF's first page is drawn in the preview
// P4: a person without an organisation (private documents) gets the same pane (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2430_docpane_ui', check, shots: 'P2430_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2430_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const key = (w, k) => w.document.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));

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

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('insurance.pdf', ['Versicherung Beispiel AG', 'Police Haftpflicht', 'Datum 01.09.2026']);
  const D2 = await upload('power.pdf', ['Stadtwerke Musterstadt', 'Abschlag Strom', 'Datum 03.10.2026']);
  const D3 = await upload('phone.pdf', ['Telefon Beispiel GmbH', 'Monatsrechnung', 'Datum 05.10.2026']);

  // ================= computer: 2.583.0 (#4835): the click opens the document view (the pane beside the list gave way to it)
  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => d.querySelectorAll('.dc-card').length === 3);
  const order = w.eval('DC.docs.map(x => x.id)');
  check(order.length === 3, 'three documents listed');
  const card = id => d.querySelector(`.dc-view [data-dco="${id}"]`);
  const paneId = () => +(d.querySelector('.dv-view .dc-body')?.dataset.id || 0);
  click(w, card(order[0]));
  check(await until(() => paneId() === order[0] && d.querySelector('.dv-view #dc-sender')), 'a click opens the document (2.583.0: in its view)');
  check(!d.querySelector('.modal') && d.querySelector('#view .dv-view') && !d.querySelector('.dc-view'), '... a page of its own, no dialog');
  check(d.querySelector(`.dv-strip [data-dvgo="${order[0]}"]`)?.classList.contains('on'), '... the open document is marked in the strip');
  check(w.location.hash === `#ablage/${order[0]}`, '... the address names the document ' + w.location.hash);
  check(d.querySelector('.dv-view .dv-pv .dv-pages') && d.querySelector('.dv-view .dv-mask .dc-form'), '... the preview and the fields');
  for (const f of ['sender', 'date', 'tags', 'folder']) check(d.querySelector(`.dv-view #dc-${f}`), `... the field ${f}`);

  // a field changed in the view saves at once, the view stays open
  const snd = d.querySelector('.dv-view #dc-sender');
  snd.value = 'Beispiel Versicherung'; snd.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/docs/${order[0]}`)).sender?.name === 'Beispiel Versicherung'), 'a field in the view saves at once');
  check(await until(() => d.querySelector('.dv-view #dc-sender')?.value === 'Beispiel Versicherung' && paneId() === order[0]), '... the view shows it and stays open');
  check(w.eval('/Sender of/.test(HIST.undo[HIST.undo.length - 1].label)'), '... one undo step');

  // the strip, the arrow keys (2.583.0: left / right), Esc
  click(w, d.querySelector(`.dv-strip [data-dvgo="${order[2]}"]`));
  check(await until(() => paneId() === order[2] && w.location.hash === `#ablage/${order[2]}`), 'a click in the strip switches the document');
  d.activeElement?.blur?.();
  key(w, 'ArrowLeft');
  check(await until(() => paneId() === order[1]), 'arrow left: the document before');
  key(w, 'ArrowLeft');
  check(await until(() => paneId() === order[0]), '... and the one before that');
  key(w, 'ArrowLeft');
  await sleep(400);
  check(paneId() === order[0], '... the first stays at the top');
  key(w, 'ArrowRight');
  check(await until(() => paneId() === order[1] && w.location.hash === `#ablage/${order[1]}`), 'arrow right: the next document');
  d.querySelector('.dv-view #dc-sender').focus();
  d.querySelector('.dv-view #dc-sender').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true}));
  await sleep(400);
  check(paneId() === order[1], '... not while typing in a field');
  d.querySelector('.dv-view #dc-sender').blur();
  key(w, 'Escape');
  check(await until(() => !d.querySelector('.dv-view') && !d.querySelector('.dc-md') && w.location.hash === '#ablage/docs'), 'Esc leaves the view, the address is #docs again');
  check(await until(() => d.querySelector(`.dc-card[data-k="dc${order[1]}"]`)?.classList.contains('dc-cur')), '... the card looked at last is marked');
  click(w, card(order[1]));
  await until(() => paneId() === order[1]);
  click(w, d.querySelector('.dv-view .dv-back[data-dc="close"]'));
  check(await until(() => !d.querySelector('.dv-view') && d.querySelector('.dc-view .dc-card')), 'the back button leaves the view');

  // choosing: Ctrl-click and the box choose; 2.768.0 (#4888): while choosing runs a plain click ticks too (rule #4612, the
  // area's one selection, like the rows) - before (2.430.0, #3582) it opened the card
  await until(() => card(order[0]));
  click(w, card(order[0]), {ctrlKey: true});
  check(await until(() => w.eval('AB.selOn') && w.eval(`AB.sel.has(${order[0]})`) && !d.querySelector('.dc-md')), 'Ctrl-click chooses the card, nothing opens');
  click(w, d.querySelector(`[data-dcchk="${order[1]}"]`));
  check(await until(() => w.eval(`AB.sel.has(${order[1]})`) && d.querySelector(`[data-dcchk="${order[1]}"]`)?.getAttribute('aria-checked') === 'true' && !d.querySelector('.dc-md')), 'the box chooses a second card');
  check(/2 selected/.test(d.querySelector('#ab-sbar')?.textContent || ''), '... the bar: 2 selected');  // 2.428.0 (#3581): the shared bar; 2.768.0 (#4888): the area's one #ab-sbar
  click(w, card(order[2]));
  check(await until(() => w.eval(`AB.sel.has(${order[2]})`) && !d.querySelector('.dv-view') && !d.querySelector('.dc-md')), 'while choosing a plain click ticks the card, nothing opens');
  check(w.eval('AB.sel.size') === 3, '... the choice holds all three');
  w.eval('ab_selEnd(); dc_draw()');
  await sleep(200);

  // an address #docs/<id> opens the view
  w.close();
  const w2 = await boot({user: 'alice', hash: `docs/${D2}`}), d2 = w2.document;
  check(await until(() => +(d2.querySelector('.dv-view .dc-body')?.dataset.id || 0) === D2 && !d2.querySelector('.modal')), 'the address #docs/<id> opens the document view');
  w2.close();

  // ================= phone: the same view, Back to the list
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), dm = m.document;
  await until(() => dm.querySelectorAll('.dc-card').length === 3);
  click(m, dm.querySelector(`[data-dco="${D3}"]`));
  check(await until(() => dm.querySelector('.dv-view #dc-sender') && !dm.querySelector('.modal.dc-md')), 'phone: the document opens as its own page');
  check(dm.querySelector('.dv-view .dv-back[data-dc="close"]'), 'phone: the page has a Back button');
  click(m, dm.querySelector('.dv-view .dv-back'));
  check(await until(() => !dm.querySelector('.dc-md') && dm.querySelector('.dc-view .dc-card')), 'phone: Back leads to the list');
  m.close();

  // ================= Firefox: the real layout
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + '#docs');
    const wait = async (js, n = 50) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    check(await wait(`document.querySelectorAll('.dc-card').length === 3`), 'Firefox: three cards');
    await ev(`(document.querySelector('.dc-view [data-dco="${D1}"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender')`), 'Firefox: the view opens');
    const r = await ev(`(() => { const m = document.querySelector('.dv-mask').getBoundingClientRect(), p = document.querySelector('.dv-pv').getBoundingClientRect(); return {mr: Math.round(m.right), pl: Math.round(p.left), pw: Math.round(p.width)}; })()`);
    check(r && r.pl >= r.mr && r.pw >= 300, 'Firefox: the preview stands right of the fields ' + JSON.stringify(r));
    check(await wait(`!!document.querySelector('.dv-pages canvas') && document.querySelector('.dv-pages canvas').width > 300`, 80), 'Firefox: the first page of the PDF is drawn in the preview');
    await shot('p2430-docpane.png');
    // the window narrowed to phone width and back: the document stays open (p2106_b_ui)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400); await ev(`(dc_draw(), 1)`); await sleep(400);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender') && document.querySelector('.dv-view').getBoundingClientRect().width >= 360 && getComputedStyle(document.querySelector('.dv-view .dv-back')).display !== 'none'`), 'Firefox: narrowed to phone width the document stays open as the page');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await sleep(400); await ev(`(dc_draw(), 1)`);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender') && getComputedStyle(document.querySelector('.dv-strip')).display !== 'none'`), '... and at full width again with the strip');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#docs');
    check(await wait(`document.querySelectorAll('.dc-card').length === 3`), 'Firefox phone: the cards');
    await ev(`(document.querySelector('.dc-view [data-dco="${D1}"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender')`), 'Firefox phone: the document opens');
    const sx = await ev(`(() => { const c = document.querySelector('.dv-view'); return {sw: c.scrollWidth, cw: c.clientWidth}; })()`);
    check(sx && sx.sw <= sx.cw + 1, 'Firefox phone: the page does not scroll sideways ' + JSON.stringify(sx));
    await shot('p2430-docpane-phone.png');
  }, true);

  console.log(`p2430_docpane_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
