/* Kalmido web client: the PDF preview (2.48.0, #1367).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   pdfView({url, name, size, dlUrl}) opens a PDF in a lightbox like the text viewer (attachments.js textView): pages
   rendered by the bundled pdf.js (static/vendor/pdfjs, loaded only when a PDF is opened, never from a CDN), page by page
   as they scroll into view; turn pages, zoom (buttons, Ctrl+wheel, pinch), swipe on a phone. Safe: same origin only,
   isEvalSupported off, nothing in the PDF runs (no scripts, no forms, links are not followed). Used by attachments,
   project files, office documents, archive PDFs and the documents / file areas. */
'use strict';

const PV_LIB = '/static/vendor/pdfjs/pdf.min.mjs', PV_WORKER = '/static/vendor/pdfjs/pdf.worker.min.mjs';
const PV_ZMIN = 0.5, PV_ZMAX = 4;
const pv_svg = d => `<svg class="i" viewBox="0 0 20 20" aria-hidden="true"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const PV_IC = {minus: pv_svg('M4 10H16'), ext: pv_svg('M11 4H16V9M16 4L9 11M14 12V16H4V6H8')};
let pv_lib = null;
function pv_load() {
  if (!pv_lib) pv_lib = import(PV_LIB).then(m => { m.GlobalWorkerOptions.workerSrc = PV_WORKER; return m; }).catch(e => { pv_lib = null; throw e; });
  return pv_lib;
}
const pv_isPdf = a => a?.mime === 'application/pdf' || /\.pdf$/i.test(String(a?.name || ''));
// 2.65.0 (#1823): the click on a preview link and pv_attr moved to lazyload.js (drawn at start, this file loads on demand)

async function pdfView(o) {
  $('.lightbox')?.remove();
  const back = document.activeElement, m = document.createElement('div');
  const url = o.url, dl = o.dlUrl || url;
  let doc = null, pages = [], base = [], fit = 1, zoom = 1, cur = 1, fail = '', io = null, gen = 0;
  m.className = 'lightbox tview pview';
  m.setAttribute('role', 'dialog'); m.setAttribute('aria-modal', 'true'); m.setAttribute('aria-label', o.name || 'PDF');
  m.innerHTML = `<div class="tvbox pvbox"><div class="tvbar pvbar"><div class="tvname"><b>${esc(o.name || 'PDF')}</b><span>${o.size ? fmtSize(o.size) : ''}</span></div>
    <span class="spacer"></span>
    <div class="pvnav" hidden><button type="button" class="iconbtn" data-pv="prev" title="${esc(tr('Previous page'))}" aria-label="${esc(tr('Previous page'))}">${ic('left')}</button>
      <span class="pvno" aria-live="polite"></span>
      <button type="button" class="iconbtn" data-pv="next" title="${esc(tr('Next page'))}" aria-label="${esc(tr('Next page'))}">${ic('right')}</button></div>
    <div class="pvzoom" hidden><button type="button" class="iconbtn" data-pv="out" title="${esc(tr('Zoom out'))}" aria-label="${esc(tr('Zoom out'))}">${PV_IC.minus}</button>
      <button type="button" class="pvpct" data-pv="fit" title="${esc(tr('Fit to width'))}"></button>
      <button type="button" class="iconbtn" data-pv="in" title="${esc(tr('Zoom in'))}" aria-label="${esc(tr('Zoom in'))}">${ic('plus')}</button></div>
    <a class="iconbtn" href="${esc(dl)}" download="${esc(o.name || '')}" title="${esc(tr('Download'))}" aria-label="${esc(tr('Download'))}">${ic('download')}</a>
    <a class="iconbtn" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(tr('Open in new tab'))}" aria-label="${esc(tr('Open in new tab'))}">${PV_IC.ext}</a>
    <button type="button" class="iconbtn" data-pv="x" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="tvbody pvbody" tabindex="-1"><div class="tvmsg muted">${tr('Loading…')}</div></div></div>`;
  const body = $('.pvbody', m);
  // the focus goes back to the link that opened it (or its new copy when the view behind was drawn again meanwhile)
  const backHref = back?.getAttribute?.('href');
  const close = () => {
    gen++; io?.disconnect(); m.remove(); try { doc?.destroy(); } catch {}
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
    pages.forEach((p, i) => { p.style.width = Math.floor(base[i].w * s) + 'px'; p.style.height = Math.floor(base[i].h * s) + 'px'; p.dataset.s = ''; p.textContent = ''; });
    status();
  };
  const draw = async (p, i) => {
    const s = fit * zoom, my = gen;
    if (p.dataset.s === String(s)) return;
    p.dataset.s = String(s);
    try {
      const page = await doc.getPage(i + 1);
      if (my !== gen || p.dataset.s !== String(s)) return;
      const vp = page.getViewport({scale: s});
      // sharp on high-density screens, capped so a big zoom on a big page stays within the canvas limits of phones
      const dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(16e6 / (vp.width * vp.height)));
      const cv = document.createElement('canvas');
      cv.width = Math.floor(vp.width * dpr); cv.height = Math.floor(vp.height * dpr);
      cv.setAttribute('aria-label', tr('Page {0}', i + 1));
      await page.render({canvas: cv, canvasContext: cv.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null}).promise;
      if (my !== gen || p.dataset.s !== String(s)) return;
      p.replaceChildren(cv);
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
    if (e.target === m || b?.dataset.pv === 'x') { close(); return; }
    if (!b || b.disabled) return;
    const a = b.dataset.pv;
    if (a === 'prev') go(cur - 1); else if (a === 'next') go(cur + 1);
    else if (a === 'in') setZoom(+(zoom * 1.25).toFixed(3)); else if (a === 'out') setZoom(+(zoom / 1.25).toFixed(3)); else if (a === 'fit') setZoom(1, false);
  });
  // own keys while the preview has the focus (Esc here also gives the focus back, events.js only removes a lightbox)
  m.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (fail || !doc || e.target.closest?.('input,textarea')) return;
    const k = e.key;
    if (k === 'ArrowRight') { e.preventDefault(); go(cur + 1); }
    else if (k === 'ArrowLeft') { e.preventDefault(); go(cur - 1); }
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
  // sideways turns the page when the page fits the width (no sideways scrolling to steal)
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
    if (quick && zoom <= 1 && Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) go(cur + (dx < 0 ? 1 : -1));
  }, {passive: true});

  document.body.appendChild(m);
  $('[data-pv="x"]', m)?.focus();
  if (o.aid) dpvSumMount(m, o);  // 2.92.0 C (#1926): "Summarise" by an agent (docpreview.js, same module)
  const my = gen;
  try {
    if (!navigator.onLine) throw new TypeError('offline');
    const r = await fetch(url, {credentials: 'same-origin'});
    if (!r.ok) throw new Error(r.status === 404 || r.status === 410 ? tr('File damaged or missing') : tr('Could not load the file'));
    const data = new Uint8Array(await r.arrayBuffer());
    const lib = await pv_load();
    if (my !== gen || !m.isConnected) return;
    // isEvalSupported off: pdf.js never builds code from the file; no scripting, links stay inert (no annotation layer)
    doc = await lib.getDocument({data, isEvalSupported: false, enableScripting: false, disableAutoFetch: true, stopAtErrors: false, useSystemFonts: true}).promise;
    if (my !== gen || !m.isConnected) { doc.destroy(); return; }
    for (let i = 1; i <= doc.numPages; i++) {
      // every page's own size (mixed formats); only the first is read up front, the others when the document is long
      const vp = i <= 30 ? (await doc.getPage(i)).getViewport({scale: 1}) : null;
      base.push(vp ? {w: vp.width, h: vp.height} : {...base[base.length - 1]});
    }
    if (my !== gen || !m.isConnected) return;
    const cs = getComputedStyle(body), avail = Math.max(200, body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2);
    fit = Math.min(2, avail / Math.max(...base.map(b => b.w)));
    body.innerHTML = `<div class="pvpages">${base.map((_, i) => `<div class="pvpage" data-i="${i}"></div>`).join('')}</div>`;
    pages = $$('.pvpage', body);
    $('.pvnav', m).hidden = $('.pvzoom', m).hidden = false;
    layout(); observe();
  } catch (e) {
    if (my !== gen || !m.isConnected) return;
    showFail(e instanceof TypeError || !navigator.onLine ? tr('The preview needs a connection. You can download the file when you are online again.')
      : e?.name === 'PasswordException' ? tr('This PDF is protected with a password and cannot be shown here.')
      : e?.name === 'InvalidPDFException' ? tr('This file cannot be shown as a PDF.')
      : e?.name === 'Error' && e.message ? e.message : tr('The preview could not be loaded.'));
  }
}
