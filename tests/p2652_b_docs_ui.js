// 2.652.0 UI test (#5070: Back closes one level at a time; #5072: the open document covers the screen on touch screens), own
// kalmido-suite:
// container (start.sh), Firefox as a touch screen in phone width (390 px, a folded Fold / an iPhone) and tablet width (840 px, an
// unfolded Fold). Invented data only. P2652B_NOSTART=1 = the container runs.
// - #5072: on a touch screen below 64rem the document opens as a page of its own (not the pane beside the list; 2.583.0, #4835:
//   the document view #docs/<id>), it fills the content area, a pull down on its preview leaves it whole (it was dragged to half
//   a window like a bottom sheet), Back brings the list at the same place
// - #5070: list -> document -> full view: one history entry per level (the view its address, the full view an overlay entry);
//   Back closes the full view, Back closes the document (no entry pushed again in between: Chrome skips such an entry and the
//   second Back left the app), Back leaves the documents
// P4: alice works without an organisation (private documents): the person without an organisation
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2652_b_docs_ui', check, shots: 'P2652B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2652B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

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
  const IDS = [];
  for (let i = 1; i <= 14; i++) IDS.push(await upload(`doc${i}.pdf`, [`Absender Beispiel ${i}`, 'Brief', `Datum ${String(i).padStart(2, '0')}.10.2026`]));
  for (const id of IDS) await call('POST', `/api/docs/${id}/review`, {done: true});

  await firefox(async ({cmd, ev, nav: go, ctx, shot, drag, until: wait}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    for (const [W, Hh] of [[390, 760], [840, 1000]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await go(B + '#docs');
      check(await wait(`document.querySelectorAll('.dc-card').length === 14`, {timeout: 20000}), `${W}: fourteen cards`);
      check(await ev(`isTouch()`), `${W}: Firefox counts as a touch screen`);
      // the list scrolled a bit first (2.583.0: Back from the view brings it back at the same place)
      await ev(`(document.getElementById('view').scrollTop = 120, 1)`);
      const v0 = await ev(`document.getElementById('view').scrollTop`);
      await ev(`(history.replaceState({p2652b: ${W}}, '', location.href), 1)`);  // marks the entry of the list (#5070: the arrow comes back to it)
      await ev(`(document.querySelector('.dc-view [data-dco="' + DC.docs[0].id + '"]').click(), 1)`);
      // #5072: the whole page, also on the tablet (it was the sticky pane .dc-pane there); 2.583.0 (#4835): the document view
      check(await wait(`!!document.querySelector('.dv-view .dv-pages') && /^#docs\\/\\d+$/.test(location.hash)`), `${W}: the document opens as a page of its own`);
      check(await ev(`!document.querySelector('.dc-pane') && !document.querySelector('.dc-view [data-dco]')`), `${W}: no pane beside the list, the list is not drawn behind it`);
      const cover = `(() => { const c = document.querySelector('.dv-view'), v = document.getElementById('view'); if (!c || !v) return null; const r = c.getBoundingClientRect(), q = v.getBoundingClientRect(), cs = getComputedStyle(v), pl = parseFloat(cs.paddingLeft) || 0, pr = parseFloat(cs.paddingRight) || 0;
        return {l: Math.round(r.left), r: Math.round(r.right), vl: Math.round(q.left), vr: Math.round(q.right), iw: innerWidth, ok: r.left <= q.left + pl + 2 && r.right >= q.right - pr - 2 - (v.offsetWidth - v.clientWidth)}; })()`;
      let c = await ev(cover);
      check(c && c.ok, `${W}: the view fills the content area ` + JSON.stringify(c));
      check(await wait(`!!document.querySelector('.dv-view .dv-pg canvas')`, {timeout: 20000}), `${W}: the sharp first page is drawn`);
      // a pull down on the preview: the view stays whole (was: a bottom sheet dragged to half)
      const box = await ev(`(() => { const r = document.querySelector('.dv-view .dv-pages').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + 30}; })()`);
      await drag(box.x, box.y, 0, Math.round(Hh * .35), 'touch');
      await wait(`!document.querySelector('.sd-drag')`, {timeout: 2000});
      c = await ev(cover);
      check(c && c.ok, `${W}: after a pull down on the preview the view still fills the content area ` + JSON.stringify(c));
      await shot(`p2652b-docpage-${W}.png`);
      await ev(`(document.querySelector('.dv-view .dv-back').click(), 1)`);
      check(await wait(`!document.querySelector('.dv-view') && !history.state?.f8d && f8d_bk.pushed === 0 && !f8d_bk.skip`), `${W}: the arrow closes the view, no overlay entry left`);
      // 2.652.0 (#5070): back on the list's own entry, no dead entry left
      check(await wait(`history.state?.p2652b === ${W} && /^#docs$/.test(location.hash)`), `${W}: the arrow leaves no dead history entry ` + await ev(`JSON.stringify({s: history.state, h: location.hash})`));
      check(await wait(`document.querySelectorAll('.dc-card').length === 14 && Math.abs(document.getElementById('view').scrollTop - ${v0}) <= 2`), `${W}: the list is back at the same place ` + await ev(`document.getElementById('view').scrollTop`));
    }

    // #5070: Back closes the top level only, list -> document -> full view (phone width, touch)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 760}});
    await go(B + '#today');
    await ev(`(location.hash = '#docs', 1)`);
    check(await wait(`document.querySelectorAll('.dc-card').length === 14`, {timeout: 20000}), 'Back: the list');
    await ev(`(document.querySelector('.dc-view [data-dco="' + DC.docs[0].id + '"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.dv-view .dv-pages') && /^#docs\\/\\d+$/.test(location.hash) && !history.state?.f8d`), 'Back: the document open with its own address (2.583.0: an entry of its own, no overlay)');
    await sleep(800);  // the end-of-swipe guard of the preview (700 ms): a tap within it is ignored on purpose
    await ev(`(() => { window.__push = 0; const p = history.pushState; history.pushState = function () { window.__push++; return p.apply(this, arguments); }; return 1; })()`);
    await ev(`(document.querySelector('.dv-view [data-dc="view"]').click(), 1)`);
    check(await wait(`!!document.querySelector('.lightbox') && history.state?.f8d === 1 && f8d_bk.pushed === 1`), 'Back: the full view open, an entry of its own ' + await ev(`JSON.stringify({s: history.state, p: f8d_bk.pushed, lb: !!document.querySelector('.lightbox')})`));
    const pushes = await ev(`window.__push`);
    await ev(`(history.back(), 1)`);
    check(await wait(`!document.querySelector('.lightbox') && !!document.querySelector('.dv-view') && f8d_bk.pushed === 0 && /^#docs\\/\\d+$/.test(location.hash)`), 'Back 1: the full view closes, the document stays');
    await sleep(300);
    check(await ev(`window.__push`) === pushes, 'Back 1: no history entry pushed again (Chrome skips it on the next Back)');
    await ev(`(history.back(), 1)`);
    check(await wait(`!document.querySelector('.dv-view') && f8d_bk.pushed === 0 && /^#docs$/.test(location.hash) && document.querySelectorAll('.dc-card').length === 14`), 'Back 2: the document closes, the list is there');
    await ev(`(history.back(), 1)`);
    check(await wait(`!/^#docs/.test(location.hash) && location.href.startsWith(${JSON.stringify(B)})`), 'Back 3: back to the view before the documents, still in Kalmido');
  }, true);

  console.log(`p2652_b_docs_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
