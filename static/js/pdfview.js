/* Kalmido web client: the PDF preview (2.48.0, #1367).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   pdfView({url, name, size, dlUrl}) opens a PDF in a lightbox like the text viewer (attachments.js textView): pages
   rendered by the bundled pdf.js (static/vendor/pdfjs, loaded only when a PDF is opened, never from a CDN), page by page
   as they scroll into view; turn pages, zoom (buttons, Ctrl+wheel, pinch), swipe on a phone. Safe: same origin only,
   isEvalSupported off, nothing in the PDF runs (no scripts, no forms, links are not followed). Used by attachments,
   project files, office documents, archive PDFs and the documents / file areas.
   2.521.0 (#4476): o.step(dir) = leaf through a list without closing (documents: docview.js dv_fullOpts, 2.583.0) - two buttons with
   o.pos ("3 of 48") and their names o.prevT / o.nextT (texts of the caller's module) and the arrow keys left / right go to the previous / next one (the pages then turn with Page up / down);
   o.img = an image instead of a PDF, o.kind 'file' = a file that cannot be shown (a hint and Download), both only with o.step.
   2.727.0 (#5202): o.peek(dir) -> {img} = the neighbour's (small) picture for the placeholder that glides along with a swipe.
   2.736.0 (#5212): o.near(dir) -> the view options of the neighbour when they are known ahead (else null, asked again a few
   times): its file is fetched and opened, the page sizes read and the first page drawn to this view's width (pv_pre), a picture
   decoded; a swipe lays exactly that beside the page and after the snap the new view takes it over in the same step (o.pre):
   no Loading…, no page drawn again. Only the direct neighbours; leafing on or closing stops and frees the rest. */
'use strict';

const PV_LIB = '/static/vendor/pdfjs/pdf.min.mjs', PV_WORKER = '/static/vendor/pdfjs/pdf.worker.min.mjs';
const PV_ZMIN = 0.5, PV_ZMAX = 4;
const pv_svg = d => `<svg class="i" viewBox="0 0 20 20" aria-hidden="true"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const PV_IC = {minus: pv_svg('M4 10H16'), ext: pv_svg('M11 4H16V9M16 4L9 11M14 12V16H4V6H8')};
let pv_lib = null, pv_libNow = null;  // 2.742.0 (#4861): pv_libNow = the loaded module (its TextLayer)
function pv_load() {
  if (!pv_lib) pv_lib = import(PV_LIB).then(m => { m.GlobalWorkerOptions.workerSrc = PV_WORKER; pv_libNow = m; return m; }).catch(e => { pv_lib = null; throw e; });
  return pv_lib;
}
// 2.549.0 (#4578): the library and the worker get a time limit (15 s, window.pv_waitMs shortens it for the tests): a worker
// that never starts on a device ends in the failure with Download instead of 'Loading…' for ever; the hung task is ended
const PV_WAIT = 15000;
function pv_timed(p, task) {
  let t = 0;
  const late = new Promise((_, no) => { t = setTimeout(() => { try { task?.destroy(); } catch {} no(Object.assign(new Error('pdf.js did not start'), {name: 'PvTimeout'})); }, window.pv_waitMs || PV_WAIT); });
  return Promise.race([p, late]).finally(() => clearTimeout(t));
}
const pv_isPdf = a => a?.mime === 'application/pdf' || /\.pdf$/i.test(String(a?.name || ''));
const PV_OPEN = {isEvalSupported: false, enableScripting: false, disableAutoFetch: true, stopAtErrors: false, useSystemFonts: true};
// one page drawn at the scale s: sharp on high-density screens, capped so a big zoom on a big page stays within the canvas limits of phones
async function pv_cv(page, s) {
  const vp = page.getViewport({scale: s}), dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(16e6 / (vp.width * vp.height)));
  const cv = document.createElement('canvas');
  cv.width = Math.floor(vp.width * dpr); cv.height = Math.floor(vp.height * dpr);
  await page.render({canvas: cv, canvasContext: cv.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null}).promise;
  return cv;
}
// every page's own size (mixed formats); only the first 30 are read up front, the others take the size of the one before
async function pv_sizes(doc) {
  const base = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const vp = i <= 30 ? (await doc.getPage(i)).getViewport({scale: 1}) : null;
    base.push(vp ? {w: vp.width, h: vp.height} : {...base[base.length - 1]});
  }
  return base;
}
const pv_fit = (body, base) => { const cs = getComputedStyle(body); return Math.min(2, Math.max(200, body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2) / Math.max(...base.map(b => b.w))); };
// 2.736.0 (#5212): a neighbour made ready ahead for the view body (its width): {url, doc, base, fit, cv} for a PDF, {url, im} for a
// picture, null for anything else or when ac stopped it; pv_preFree lets go of the opened file
async function pv_pre(n, body, ac) {
  if (!n || n.kind === 'file' || (!n.img && !n.url) || !navigator.onLine) return null;
  const st = () => ac.signal.aborted;
  if (n.img) { const im = new Image(); im.className = 'pvimg'; im.alt = n.name || ''; im.src = n.img; await im.decode().catch(() => {}); return st() ? null : {url: n.url, im}; }
  const sp = typeof ofc_spUrl === 'function' ? ofc_spUrl : u => u;
  const r = await fetch(sp(n.url), {credentials: 'same-origin', signal: ac.signal}); if (!r.ok || st()) return null;
  const data = new Uint8Array(await r.arrayBuffer()), lib = await pv_timed(pv_load()); if (st()) return null;
  const task = lib.getDocument({data, ...PV_OPEN}), doc = await pv_timed(task.promise, task);
  try {
    const base = await pv_sizes(doc); if (st()) throw 0;
    const fit = pv_fit(body, base), cv = await pv_cv(await doc.getPage(1), fit); if (st()) throw 0;
    cv.setAttribute('aria-label', tr('Page {0}', 1));
    return {url: n.url, doc, base, fit, cv};
  } catch { try { doc.destroy(); } catch {} return null; }
}
const pv_preFree = v => { try { v?.doc?.destroy(); } catch {} };
// the pages of a view in their final size (CSSOM, no inline style attribute); a canvas drawn ahead goes on the first one
function pv_pagesEl(base, s, cv) {
  const w = document.createElement('div'); w.className = 'pvpages';
  base.forEach((b, i) => { const p = document.createElement('div'); p.className = 'pvpage'; p.dataset.i = String(i); p.style.width = Math.floor(b.w * s) + 'px'; p.style.height = Math.floor(b.h * s) + 'px'; w.appendChild(p); });
  if (cv && w.firstChild) { /** @type {HTMLElement} */ (w.firstChild).dataset.s = String(s); w.firstChild.appendChild(cv); }
  return w;
}
// what a swipe lays beside the page: the view body as the neighbour will stand (built once)
function pv_preEl(v) {
  if (v.el) return v.el;
  const el = document.createElement('div');
  el.className = 'tvbody pvbody'; el.style.cssText = 'width:100%;height:100%;box-sizing:border-box;overflow:hidden';
  if (v.im) { const w = document.createElement('div'); w.className = 'pvimgw'; w.appendChild(v.im.cloneNode()); el.appendChild(w); }
  else el.appendChild(pv_pagesEl(v.base, v.fit, v.cv));
  return (v.el = el);
}
// 2.65.0 (#1823): the click on a preview link and pv_attr moved to lazyload.js (drawn at start, this file loads on demand)

// ---- 2.742.0 (#4861): the text of a page can be marked and copied as in a PDF program: over each drawn canvas lies the
// invisible text layer of pdf.js (TextLayer; its spans carry the text as textContent, never as markup), at the page's scale
// (--scale-factor; a zoom draws page and layer anew), freed with the page. Returns the layer, or null; host._pvnt = true when
// the page has no text at all (a scan: the caller offers the recognised text instead).
async function pv_text(lib, page, vp, host, live) {
  if (!lib?.TextLayer) return null;
  let tc; try { tc = await page.getTextContent(); } catch { return null; }
  if (!live()) return null;
  host._pvnt = !tc.items.some(x => /** @type {any} */ (x).str?.trim());
  if (host._pvnt) return null;
  const tl = document.createElement('div');
  tl.className = 'textLayer';
  tl.style.setProperty('--scale-factor', String(vp.scale));
  try { await new lib.TextLayer({textContentSource: tc, container: tl, viewport: vp}).render(); } catch { return null; }
  if (!live()) return null;
  const end = document.createElement('div'); end.className = 'endOfContent'; tl.append(end);
  host.querySelector(':scope > .textLayer')?.remove();
  host.append(tl);
  return tl;
}
// a zoom changed the page boxes: the layers drawn at the old scale follow at once (until the page is drawn anew)
function pv_textScale(root, s) { for (const tl of root.querySelectorAll('.textLayer')) /** @type {HTMLElement} */ (tl).style.setProperty('--scale-factor', String(s)); }
// the text of every page (Cmd / Ctrl+A copies all of them, also the ones far away without a layer)
async function pv_allText(doc, live) {
  const out = [];
  for (let i = 1; i <= Math.min(doc.numPages, 2000); i++) {
    const tc = await (await doc.getPage(i)).getTextContent(); if (!live()) return null;
    out.push(tc.items.map(x => (/** @type {any} */ (x).str || '') + (/** @type {any} */ (x).hasEOL ? '\n' : '')).join('').trim());
  }
  return out.filter(Boolean).join('\n\n');
}
// Cmd / Ctrl+A inside a preview: the drawn pages' text is marked, the copy gets the text of all pages
function pv_selAll(doc, col) {
  const sel = getSelection(); if (!sel || !col) return;
  const r = document.createRange(); r.selectNodeContents(col); sel.removeAllRanges(); sel.addRange(r);
  const my = col._pvag = (col._pvag || 0) + 1, q = sel.rangeCount ? sel.getRangeAt(0) : r; col._pvall = null;
  col._pvr = [q.startContainer, q.startOffset, q.endContainer, q.endOffset];  // as the browser keeps it (a copy compares)
  pv_allText(doc, () => col.isConnected && col._pvag === my).then(t => { if (t != null && col._pvag === my) col._pvall = t; }).catch(() => {});
}
document.addEventListener('copy', e => {
  const sel = getSelection(); if (!sel || sel.rangeCount !== 1) return;
  const r = sel.getRangeAt(0), col = /** @type {any} */ (r.commonAncestorContainer)?.closest?.('.dv-pgcol, .pvpages'), k = col?._pvr;
  if (!col?._pvall || !k || r.startContainer !== k[0] || r.startOffset !== k[1] || r.endContainer !== k[2] || r.endOffset !== k[3]) return;  // the marking of Ctrl+A, unchanged
  e.clipboardData?.setData('text/plain', col._pvall); e.preventDefault();
});
document.addEventListener('pointerdown', e => {  // as pdf.js' viewer: while marking, the end of the layer covers the page (no jumps)
  const tl = /** @type {any} */ (e.target).closest?.('.textLayer'); if (tl) tl.classList.add('selecting');
});
document.addEventListener('pointerup', () => { for (const tl of document.querySelectorAll('.textLayer.selecting')) tl.classList.remove('selecting'); });

async function pdfView(o) {
  $('.lightbox')?.remove();
  const back = o.back || document.activeElement, m = document.createElement('div');
  const sp = typeof ofc_spUrl === 'function' ? ofc_spUrl : u => u, url = o.url ? sp(o.url) : o.url, dl = o.dlUrl ? sp(o.dlUrl) : url;  // 2.577.0 (#4638, review): the office's open area
  let doc = null, pages = [], base = [], fit = 1, zoom = 1, cur = 1, fail = '', io = null, gen = 0;
  m.className = 'lightbox tview pview';
  m.setAttribute('role', 'dialog'); m.setAttribute('aria-modal', 'true'); m.setAttribute('aria-label', o.name || 'PDF');
  m.innerHTML = `<div class="tvbox pvbox"><div class="tvbar pvbar"><div class="tvname"><b>${esc(o.name || 'PDF')}</b><span>${o.size ? fmtSize(o.size) : ''}</span></div>
    <span class="spacer"></span>
    ${o.step ? `<div class="pvdocs" role="group" aria-label="${esc(o.pos || '')}"><button type="button" class="iconbtn" data-pv="dprev" title="${esc(o.prevT || '')}" aria-label="${esc(o.prevT || '')}"${o.first ? ' disabled' : ''}>${ic('left')}</button>
      <span class="pvdno">${esc(o.pos || '')}</span>
      <button type="button" class="iconbtn" data-pv="dnext" title="${esc(o.nextT || '')}" aria-label="${esc(o.nextT || '')}"${o.last ? ' disabled' : ''}>${ic('right')}</button></div>` : '' /* 2.521.0 (#4476) */}
    <div class="pvnav" hidden><button type="button" class="iconbtn" data-pv="prev" title="${esc(tr('Previous page'))}" aria-label="${esc(tr('Previous page'))}">${ic('left')}</button>
      <span class="pvno" aria-live="polite"></span>
      <button type="button" class="iconbtn" data-pv="next" title="${esc(tr('Next page'))}" aria-label="${esc(tr('Next page'))}">${ic('right')}</button></div>
    <div class="pvzoom" hidden><button type="button" class="iconbtn" data-pv="out" title="${esc(tr('Zoom out'))}" aria-label="${esc(tr('Zoom out'))}">${PV_IC.minus}</button>
      <button type="button" class="pvpct" data-pv="fit" title="${esc(tr('Fit to width'))}"></button>
      <button type="button" class="iconbtn" data-pv="in" title="${esc(tr('Zoom in'))}" aria-label="${esc(tr('Zoom in'))}">${ic('plus')}</button></div>
    ${o.arch ? `<button type="button" class="iconbtn" data-pv="arch" title="${esc(tr('Correct archived document'))}" aria-label="${esc(tr('Correct archived document'))}">${ic('edit')}</button>` : '' /* 2.451.0 (#3834) */}
    <a class="iconbtn" href="${esc(dl)}" download="${esc(o.name || '')}" title="${esc(tr('Download'))}" aria-label="${esc(tr('Download'))}">${ic('download')}</a>
    ${typeof mw_desk === 'function' && mw_desk() ? `<a class="iconbtn" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(tr('Open in new tab'))}" aria-label="${esc(tr('Open in new tab'))}">${PV_IC.ext}</a>` : '' /* 2.537.0 (#4574): only with a mouse */}
    <button type="button" class="iconbtn" data-pv="x" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="tvbody pvbody" tabindex="-1"><div class="tvmsg muted">${tr('Loading…')}</div></div></div>`;
  const body = $('.pvbody', m);
  // the focus goes back to the link that opened it (or its new copy when the view behind was drawn again meanwhile)
  const backHref = back?.getAttribute?.('href');
  const close = () => {
    gen++; io?.disconnect(); m.remove(); try { doc?.destroy(); } catch {}
    pre_free();  // 2.736.0 (#5212)
    (back?.isConnected ? back : backHref && $$('[data-pview]').find(x => x.getAttribute('href') === backHref))?.focus?.();
  };
  const showFail = msg => {
    fail = msg;
    body.innerHTML = `<div class="pvfail">${ic('pdf')}<p>${esc(msg)}</p><a class="btn pri" href="${esc(dl)}" download="${esc(o.name || '')}">${ic('download')} ${esc(tr('Download'))}</a></div>`;
    $('.pvnav', m).hidden = $('.pvzoom', m).hidden = true;
  };
  const status = () => {
    $('.pvno', m).textContent = tr('Page {0} of {1}', cur, pages.length);
    $('.pvpct', m).textContent = Math.round(fit * zoom * 100) + ' %';
    $('[data-pv="prev"]', m).disabled = cur <= 1; $('[data-pv="next"]', m).disabled = cur >= pages.length;
  };
  // page boxes have their final size before anything is drawn (no jumps); a box is drawn when it comes near the view
  const layout = () => {
    const s = fit * zoom;
    pages.forEach((p, i) => { p.style.width = Math.floor(base[i].w * s) + 'px'; p.style.height = Math.floor(base[i].h * s) + 'px'; if (p.dataset.s !== String(s)) { p.dataset.s = ''; p.textContent = ''; } });  // 2.736.0 (#5212): a page drawn ahead at this scale stays
    status();
    if (swn) body.style.touchAction = zoom <= 1 ? 'pan-y' : '';  // 2.652.0 (#5071): sideways is the swipe; enlarged the page scrolls both ways
  };
  const draw = async (p, i) => {
    const s = fit * zoom, my = gen;
    if (p.dataset.s === String(s)) return;
    p.dataset.s = String(s);
    try {
      const page = await doc.getPage(i + 1);
      if (my !== gen || p.dataset.s !== String(s)) return;
      const cv = await pv_cv(page, s);  // 2.736.0 (#5212): shared with the neighbour drawn ahead
      cv.setAttribute('aria-label', tr('Page {0}', i + 1));
      if (my !== gen || p.dataset.s !== String(s)) return;
      p.replaceChildren(cv);
      pv_text(pv_libNow, page, vp, p, () => my === gen && p.dataset.s === String(s) && p.isConnected);  // 2.742.0 (#4861)
    } catch (e) { if (my === gen) { p.dataset.s = ''; p.innerHTML = `<span class="pvperr">${esc(tr('This page could not be shown'))}</span>`; } }
  };
  const go = n => { n = Math.max(1, Math.min(pages.length, n)); pages[n - 1]?.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); cur = n; status(); };
  const setZoom = (z, keep = true) => {
    z = Math.max(PV_ZMIN, Math.min(PV_ZMAX, z));
    if (!doc || z === zoom) return;
    const top = body.scrollTop / Math.max(1, body.scrollHeight);
    zoom = z; gen++; layout();
    if (keep) body.scrollTop = top * body.scrollHeight;
    observe();
  };
  const observe = () => {
    io?.disconnect();
    io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) draw(en.target, +en.target.dataset.i); }), {root: body, rootMargin: '600px 0px'});
    pages.forEach(p => io.observe(p));
  };
  const curFromScroll = () => {
    const mid = body.scrollTop + body.clientHeight / 3;
    let n = 1; for (const p of pages) { if (p.offsetTop <= mid) n = +p.dataset.i + 1; else break; }
    if (n !== cur) { cur = n; status(); }
  };

  m.addEventListener('click', e => {
    const b = e.target.closest('[data-pv]');
    if (e.target === m && swn?.recent()) return;  // 2.652.0 (#5071): the end of a swipe is no tap
    if (e.target === m || b?.dataset.pv === 'x') { close(); return; }
    if (b?.dataset.pv === 'arch') { close(); r81b_archEdit(o.arch); return; }
    if (!b || b.disabled) return;
    const a = b.dataset.pv;
    if (a === 'dprev' || a === 'dnext') { leaf(a === 'dnext' ? 1 : -1); return; }
    if (a === 'prev') go(cur - 1); else if (a === 'next') go(cur + 1);
    else if (a === 'in') setZoom(+(zoom * 1.25).toFixed(3)); else if (a === 'out') setZoom(+(zoom / 1.25).toFixed(3)); else if (a === 'fit') setZoom(1, false);
  });
  // 2.736.0 (#5212): the direct neighbours made ready ahead (dir -> {ac, v}); asked again a few times while their data are on the way
  /** @type {any} */
  const PRE = {};
  m._pre = PRE;  // (the tests look at what is made ready)
  const pre_free = () => { for (const k of Object.keys(PRE)) { PRE[k].ac.abort(); pv_preFree(PRE[k].v); delete PRE[k]; } };
  const ahead = (k = 0) => {
    if (!o.near || !m.isConnected) return;
    let wait = false;
    for (const dir of [1, -1]) {
      if (PRE[dir] || (dir > 0 ? o.last : o.first)) continue;
      const n = o.near(dir); if (!n) { wait = true; continue; }
      const e = PRE[dir] = {ac: new AbortController(), v: null};
      pv_pre(n, body, e.ac).then(v => { if (PRE[dir] === e && m.isConnected) e.v = v; else pv_preFree(v); }, () => {});
    }
    if (wait && k < 15) setTimeout(() => ahead(k + 1), 400);
  };
  // 2.521.0 (#4476): the previous / next one of the list in the same place; the one that opened it keeps the focus back
  let leafing = false;
  const leaf = async dir => {
    if (!o.step || leafing) return;
    leafing = true;
    const n = await o.step(dir).catch(() => null);
    leafing = false;
    if (!n || !m.isConnected) return;
    const f = document.activeElement?.dataset?.pv;
    const p = PRE[dir]?.v, use = p && p.url === n.url && !n.data ? p : null;  // 2.736.0 (#5212): made ready ahead
    if (use) PRE[dir].v = null;
    gen++; io?.disconnect(); try { doc?.destroy(); } catch {}
    pre_free();
    pdfView({...n, back, pre: use});  // its first part (the new box, the focus) runs at once
    const lb = $('.lightbox.pview'); if (f && lb) $(`[data-pv="${f}"]:not([disabled])`, lb)?.focus();
  };
  // 2.652.0 (#5071): on a touch screen (phone, tablet, any width) a swipe sideways leafs through the list (swipenav.js, the
  // gesture of the document preview); enlarged (zoom over the width) one finger moves the page as before
  // 2.727.0 (#5202): the neighbour lies beside it as a placeholder (o.peek(dir) -> {img} its small picture, else an empty
  // page) and glides along; let go, it snaps fully into place and only then loads (the placeholder stays until it is there)
  // 2.736.0 (#5212): the neighbour made ready ahead lies there as it will stand (pv_preEl); else the placeholder as before
  const swn = o.step && typeof swn_attach === 'function' ? swn_attach(body, {area: () => zoom <= 1 ? body : null,
    can: dir => !(dir > 0 ? o.last : o.first), go: dir => leaf(dir), peek: dir => (PRE[dir]?.v ? {el: pv_preEl(PRE[dir].v)} : o.peek ? o.peek(dir) : null)}) : null;
  if (swn) body.style.touchAction = 'pan-y';
  // own keys while the preview has the focus (Esc here also gives the focus back, events.js only removes a lightbox)
  m.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.target.closest?.('input,textarea')) return;
    const k = e.key;
    if ((e.ctrlKey || e.metaKey) && !e.altKey && k.toLowerCase() === 'a' && doc && !fail) { e.preventDefault(); e.stopPropagation(); pv_selAll(doc, $('.pvpages', body)); return; }  // 2.742.0 (#4861): every page
    if (o.step && (k === 'ArrowRight' || k === 'ArrowLeft') && !e.altKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); leaf(k === 'ArrowRight' ? 1 : -1); return; }
    if (fail || !doc) return;
    if (k === 'ArrowRight' || (o.step && k === 'PageDown')) { e.preventDefault(); go(cur + 1); }
    else if (k === 'ArrowLeft' || (o.step && k === 'PageUp')) { e.preventDefault(); go(cur - 1); }
    else if (k === '+' || k === '=') { e.preventDefault(); setZoom(zoom * 1.25); }
    else if (k === '-') { e.preventDefault(); setZoom(zoom / 1.25); }
    else if (k === '0') { e.preventDefault(); setZoom(1, false); }
    else if (k === 'Home' || k === 'End') { e.preventDefault(); go(k === 'Home' ? 1 : pages.length); }
    else if (k === 'Tab') {  // the focus stays inside the dialog
      const f = $$('button:not([disabled]):not([hidden]),a[href],[tabindex="0"]', m).filter(x => x.offsetParent);
      if (f.length && e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (f.length && !e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  body.addEventListener('scroll', () => { if (doc) curFromScroll(); }, {passive: true});
  body.addEventListener('wheel', e => { if (!doc || !(e.ctrlKey || e.metaKey)) return; e.preventDefault(); setZoom(zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1)); }, {passive: false});
  // touch: two fingers pinch (the pages scale live with a transform, drawn sharp again at the end); one finger swiped
  // sideways turns the page when the page fits the width (no sideways scrolling to steal); 2.652.0 (#5071): not while leafing (o.step: the swipe above)
  let t0 = null;
  body.addEventListener('touchstart', e => {
    if (!doc) return;
    const t = e.touches;
    t0 = t.length === 2 ? {pinch: Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY), r: 1}
      : t.length === 1 ? {x: t[0].clientX, y: t[0].clientY, at: Date.now()} : null;
  }, {passive: true});
  body.addEventListener('touchmove', e => {
    if (!t0?.pinch || e.touches.length !== 2) return;
    e.preventDefault();
    const t = e.touches, d = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
    t0.r = Math.max(PV_ZMIN / zoom, Math.min(PV_ZMAX / zoom, d / t0.pinch));
    const w = $('.pvpages', body); if (w) w.style.transform = `scale(${t0.r})`;
  }, {passive: false});
  body.addEventListener('touchend', e => {
    if (!t0) return;
    if (t0.pinch) { const w = $('.pvpages', body); if (w) w.style.transform = ''; if (e.touches.length < 2) { const r = t0.r; t0 = null; if (Math.abs(r - 1) > 0.02) setZoom(zoom * r); } return; }
    const c = e.changedTouches[0], dx = c.clientX - t0.x, dy = c.clientY - t0.y, quick = Date.now() - t0.at < 600;
    t0 = null;
    if (quick && zoom <= 1 && !swn && Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) go(cur + (dx < 0 ? 1 : -1));
  }, {passive: true});

  document.body.appendChild(m);
  $('[data-pv="x"]', m)?.focus();
  if (o.aid) dpvSumMount(m, o);  // 2.92.0 C (#1926): "Summarise" by an agent (docpreview.js, same module)
  const my = gen;
  if (o.img || o.kind === 'file') {  // 2.521.0 (#4476): leafing reached an image / a file that is no PDF
    if (o.pre?.im) { const w = document.createElement('div'); w.className = 'pvimgw'; w.appendChild(o.pre.im); body.replaceChildren(w); }  // 2.736.0 (#5212): decoded ahead
    else if (o.img) body.innerHTML = `<div class="pvimgw"><img class="pvimg" src="${esc(o.img)}" alt="${esc(o.name || '')}"></div>`;
    else showFail(tr('This file cannot be shown here. You can download it.'));
    ahead();
    return;
  }
  if (o.pre?.doc) {  // 2.736.0 (#5212): opened and its first page drawn ahead: shown in this same step, nothing loads or is drawn again
    doc = o.pre.doc; base = o.pre.base; fit = pv_fit(body, base);
    body.replaceChildren(pv_pagesEl(base, fit, Math.abs(fit - o.pre.fit) < 0.002 ? o.pre.cv : null));
    pages = $$('.pvpage', body);
    $('.pvnav', m).hidden = $('.pvzoom', m).hidden = false;
    layout(); observe(); ahead();
    return;
  }
  try {
    if (!navigator.onLine && !o.data) throw new TypeError('offline');
    const r = o.data ? null : await fetch(url, {credentials: 'same-origin'});  // 2.353.0 A (#2758): o.data = bytes decrypted in the browser
    if (r && !r.ok) throw new Error(r.status === 404 || r.status === 410 ? tr('File damaged or missing') : tr('Could not load the file'));
    const data = o.data || new Uint8Array(await r.arrayBuffer());
    // 2.549.0 (#4578, review): a library import that timed out is forgotten, the next opening tries again
    const lib = await pv_timed(pv_load()).catch(e => { if (e.name === 'PvTimeout') pv_lib = null; throw e; });
    if (my !== gen || !m.isConnected) return;
    // isEvalSupported off: pdf.js never builds code from the file; no scripting, links stay inert (no annotation layer)
    const task = lib.getDocument({data, ...PV_OPEN});
    // 2.549.0 (#4578): a worker that fails ("Setting up fake worker failed") or never answers is no message for the user
    doc = await pv_timed(task.promise, task).catch(e => { throw e?.name === 'PasswordException' || e?.name === 'InvalidPDFException' ? e : Object.assign(new Error(String(e?.message || e)), {name: 'PvWorker'}); });
    if (my !== gen || !m.isConnected) { doc.destroy(); return; }
    base = await pv_sizes(doc);  // 2.736.0 (#5212): shared with the neighbour made ready ahead
    if (my !== gen || !m.isConnected) return;
    fit = pv_fit(body, base);
    body.innerHTML = `<div class="pvpages">${base.map((_, i) => `<div class="pvpage" data-i="${i}"></div>`).join('')}</div>`;
    pages = $$('.pvpage', body);
    $('.pvnav', m).hidden = $('.pvzoom', m).hidden = false;
    layout(); observe(); ahead();
  } catch (e) {
    if (my !== gen || !m.isConnected) return;
    showFail(e instanceof TypeError || !navigator.onLine ? tr('The preview needs a connection. You can download the file when you are online again.')
      : e?.name === 'PasswordException' ? tr('This PDF is protected with a password and cannot be shown here.')
      : e?.name === 'InvalidPDFException' ? tr('This file cannot be shown as a PDF.')
      : e?.name === 'Error' && e.message ? e.message : tr('The preview could not be loaded.'));
  }
}
