// @ts-check
/* Kalmido web client: Documents, the reading view and the widths of the pane (2.521.0, #4476, includes #4399).
   Computer only (a window of 64rem and more; phones and narrow windows stay as they were): the button "Read" in the bar of
   the list turns the open document's pane into the main part of the page - the list becomes a narrow column (sender, date,
   type; search, filters and "To review" stay on top), the preview fills the height (every page of a PDF, scrollable,
   zoomable with the buttons, Ctrl + wheel and + / -), the properties stand as a column beside it (a wide pane) or below it,
   folded away with one button. The arrow keys up / down leaf on as before (docs.js dc_step), the full screen "Show" leafs with
   the arrow keys left / right and two buttons (pdfview.js o.step). Grips set the width of the pane (also outside the reading
   view, #4399), of the list column and of the properties; dragged or moved with the arrow keys, a double click (Home) = the
   standard width. The view, the widths and the folded properties are kept per device (localStorage).
   Part of the module docs (lazyload.js); docs.js asks it through typeof checks. Classic script sharing the global scope. */
'use strict';

const DCR = {rz: 1, pdf: null, ro: null, drag: null};
const DCR_ZMIN = 0.5, DCR_ZMAX = 4;
// the grips: their device key, the CSS variable on .dc-wrap, the room the others keep (rem)
// 2.582.0 (#4830): no fixed limits, only the neighbour's minimum: the properties beside the preview keep the preview a small
// rest (DCR_PV_MIN, docs.css .dc-rd .dc-top) plus the gap, no longer 20rem
const DCR_PV_MIN = 12;
const DCR_GRIPS = {pane: {k: 'dc.paneW', v: '--dc-pw', min: 20, keep: 18}, list: {k: 'dc.readW', v: '--dc-rl', min: 14, keep: 30}, props: {k: 'dc.propW', v: '--dc-ew', min: 16, keep: DCR_PV_MIN + 1}};
const dcr_rem = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
const dcr_wide = () => !isMobile() && matchMedia('(min-width:64rem)').matches;
const dcr_want = () => !!LS.get('dc.read', false);
const dcr_on = () => dcr_want() && dcr_wide();
const dcr_propsOff = () => !!LS.get('dc.readProps', false);

// ---- the button and the frame of the view (viewDocs)
function dcr_btnHtml() {
  if (!dcr_wide()) return '';
  const on = dcr_want();
  return `<button type="button" class="btn sm dc-readb${on ? ' on' : ''}" data-dc="read" aria-pressed="${on}" title="${esc(tr('Reading view: a large preview beside a narrow list'))}">${ic('book', 's')} <span>${tr('Read')}</span></button>`;
}
function dcr_wrapAttr(pane) {  // the class and the kept widths of .dc-wrap (inside its class attribute)
  if (!pane || isMobile()) return '';
  const st = Object.values(DCR_GRIPS).map(g => { const px = +LS.get(g.k, 0); return px > 0 ? `${g.v}:${Math.round(px)}px` : ''; }).filter(Boolean).join(';');
  return (dcr_on() ? ' dc-read' : '') + (st ? `" style="${st}` : '');
}
const dcr_gripHtml = (which, label) => `<button type="button" class="dc-grip" data-dcgrip="${which}" aria-label="${esc(label + ': ' + tr('Resize (arrow keys; double-click: default size)'))}" title="${esc(tr('Drag to resize · double-click: default size'))}"></button>`;
function dcr_paneGrip(pane) {  // between the list and the pane: the width of the pane, in the reading view the list's
  if (!pane || isMobile()) return '';
  return dcr_on() ? dcr_gripHtml('list', tr('Documents')) : dcr_gripHtml('pane', tr('Properties'));
}
function dcr_toggle() {
  const on = !dcr_want();
  if (on) LS.set('dc.read', true); else LS.del('dc.read');
  if (on && !DC.paneId && DC.docs?.length) { dc_open(DC.docs[0].id, {pane: true}); return; }  // nothing open: the first one of the list
  dcr_redraw();
}
function dcr_redraw() {  // the list and the pane anew (the preview is another element in the reading view)
  if (!dcr_isDocs()) return;
  dc_draw();
  const p = $('.dc-pane'); if (p && DC.doc) { const b = $('.dc-body', p); if (b) b.dataset.id = ''; dc_mdDraw(p); }
  $('.dc-view [data-dc="read"]')?.focus({preventScroll: true});
}
const dcr_isDocs = () => S.route.mod === 'docs';
// a window made wider / narrower than the reading view's width: the view follows
let dcr_was = null;
window.addEventListener('resize', () => {
  const now = dcr_on(); if (dcr_was === null) { dcr_was = now; return; }
  if (now === dcr_was) return;
  dcr_was = now;
  if (dcr_isDocs() && $('.dc-view')) dcr_redraw();
});

// ---- the sheet of the document in the reading view (dc_mdDraw): the head button, the preview
const dcr_inPane = md => !!md?.classList?.contains('dc-pane') && dcr_on();
function dcr_headBtn(md) {
  if (!dcr_inPane(md)) return '';
  const off = dcr_propsOff();
  return `<button type="button" class="iconbtn dc-rpb" data-dc="rprops" aria-expanded="${!off}" aria-controls="dc-props" aria-label="${esc(off ? tr('Show properties') : tr('Hide properties'))}" title="${esc(off ? tr('Show properties') : tr('Hide properties'))}">${ic(off ? 'panelshow' : 'panelhide')}</button>`;
}
function dcr_prevHtml(d) {
  const pct = Math.round(DCR.rz * 100);
  return `<div class="dc-rvbar" role="group" aria-label="${esc(tr('Zoom'))}"><button type="button" class="iconbtn" data-dc="rz:out" aria-label="${esc(tr('Zoom out'))}" title="${esc(tr('Zoom out'))}"${DCR.rz <= DCR_ZMIN ? ' disabled' : ''}>${ic('minus', 's')}</button><button type="button" class="btn sm dc-rzp" data-dc="rz:fit" title="${esc(tr('Fit to width'))}">${pct} %</button><button type="button" class="iconbtn" data-dc="rz:in" aria-label="${esc(tr('Zoom in'))}" title="${esc(tr('Zoom in'))}"${DCR.rz >= DCR_ZMAX ? ' disabled' : ''}>${ic('plus', 's')}</button></div>
    <div class="dc-rv" data-fl-fill tabindex="0" role="region" aria-label="${esc(tr('Show {0}', d.name))}"></div>`;
}
function dcr_zoom(md, z) {
  z = Math.max(DCR_ZMIN, Math.min(DCR_ZMAX, +z.toFixed(3)));
  if (z === DCR.rz) return;
  DCR.rz = z;
  const bar = $('.dc-rvbar', md);
  if (bar) {
    $('.dc-rzp', bar).textContent = Math.round(z * 100) + ' %';
    $('[data-dc="rz:out"]', bar).disabled = z <= DCR_ZMIN; $('[data-dc="rz:in"]', bar).disabled = z >= DCR_ZMAX;
  }
  dcr_layout($('.dc-rv', md), true);
}
function dcr_click(a, md) {  // true = handled (dc_mdClick)
  if (a === 'rprops') {
    const off = !dcr_propsOff();
    if (off) LS.set('dc.readProps', true); else LS.del('dc.readProps');
    $('.dc-main', md)?.classList.toggle('dc-pcol', off);
    const b = $('[data-dc="rprops"]', md);
    if (b) { const t = off ? tr('Show properties') : tr('Hide properties'); b.setAttribute('aria-expanded', String(!off)); b.setAttribute('aria-label', t); b.title = t; b.innerHTML = ic(off ? 'panelshow' : 'panelhide'); }
    requestAnimationFrame(() => dcr_layout($('.dc-rv', md)));
    return true;
  }
  if (a.startsWith('rz:')) { const k = a.slice(3); dcr_zoom(md, k === 'fit' ? 1 : k === 'in' ? DCR.rz * 1.25 : DCR.rz / 1.25); return true; }
  return false;
}

// ---- the preview of the reading view: an image as itself, a PDF with every page (drawn when it comes near), else the small picture
function dcr_free() { try { DCR.pdf?.doc?.destroy(); } catch { /* gone */ } DCR.pdf?.io?.disconnect(); DCR.pdf = null; }
async function dcr_pvDraw(md, d) {
  const box = $('.dc-rv', md); if (!box) return;
  const key = `${d.id}:${d.size}`;
  if (box._pv === key && box.firstChild) return;
  box._pv = key;
  if (DCR.pdf && DCR.pdf.box !== box) dcr_free();
  if (!DCR.ro && typeof ResizeObserver === 'function') DCR.ro = new ResizeObserver(es => { for (const e of es) if (e.target.isConnected) dcr_layout(e.target); });
  DCR.ro?.observe(box);
  const live = () => box.isConnected && box._pv === key;
  box.innerHTML = d.thumb ? `<div class="dc-rpg dc-rimg"><img src="/api/docs/${d.id}/thumb?v=${esc(d.updated_at || '')}" alt=""></div>` : `<span class="dc-ph">${ic(dc_isPdf(d) ? 'file' : 'picture')}</span>`;
  if (/^image\//.test(d.mime || '') && d.thumb) {
    const im = new Image(); im.alt = '';
    im.onload = () => { if (!live()) return; const p = document.createElement('div'); p.className = 'dc-rpg dc-rimg'; p.appendChild(im); box.replaceChildren(p); box._base = [{w: im.naturalWidth || 600, h: im.naturalHeight || 800}]; dcr_layout(box, false, true); };
    im.src = dc_fileUrl(d);
    return;
  }
  if (!dc_isPdf(d) || d.size > 40e6 || typeof loadModule !== 'function') return;
  try {
    await loadModule('pdf');
    const lib = typeof pv_load === 'function' ? await pv_load() : null; if (!lib || !live()) return;
    const r = await fetch(dc_fileUrl(d), {credentials: 'same-origin'}); if (!r.ok || !live()) return;
    // as in pdfview.js: nothing in the file runs (no eval, no scripts, no links)
    const doc = await lib.getDocument({data: new Uint8Array(await r.arrayBuffer()), isEvalSupported: false, enableScripting: false, disableAutoFetch: true, stopAtErrors: false, useSystemFonts: true}).promise;
    if (!live()) { doc.destroy(); return; }
    const base = [];
    for (let i = 1; i <= doc.numPages; i++) {  // every page's own size; the first 30 read up front, later ones like the one before
      const vp = i <= 30 ? (await doc.getPage(i)).getViewport({scale: 1}) : null;
      base.push(vp ? {w: vp.width, h: vp.height} : {...base[base.length - 1]});
      if (!live()) { doc.destroy(); return; }
    }
    dcr_free();
    DCR.pdf = {doc, box, gen: 0};
    box._base = base;
    box.innerHTML = base.map((_, i) => `<div class="dc-rpg" data-i="${i}"></div>`).join('');
    box.dataset.pages = String(base.length);
    dcr_layout(box, false, true);
  } catch { /* the small picture stays */ }
}
// the pages get their final size before they are drawn (no jumps): the width of the box times the zoom
function dcr_layout(box, keep, force) {
  if (!box?.isConnected || !box._base) return;
  const cs = getComputedStyle(box), avail = Math.max(160, box.clientWidth - parseFloat(cs.paddingLeft || '0') - parseFloat(cs.paddingRight || '0') - 2);
  if (!force && !keep && Math.abs((box._aw || 0) - avail) < 2) return;
  box._aw = avail;
  const fit = Math.min(2, avail / Math.max(...box._base.map(b => b.w))), s = fit * DCR.rz, top = box.scrollTop / Math.max(1, box.scrollHeight);
  const pages = $$('.dc-rpg', box);
  pages.forEach((p, i) => { const b = box._base[i] || box._base[0]; p.style.width = Math.floor(b.w * s) + 'px'; p.style.height = Math.floor(b.h * s) + 'px'; });
  if (keep) box.scrollTop = top * box.scrollHeight;
  const pdf = DCR.pdf; if (!pdf || pdf.box !== box) return;
  pdf.gen++; pdf.s = s;
  for (const p of pages) { p.dataset.s = ''; }
  pdf.io?.disconnect();
  pdf.io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) dcr_page(pdf, en.target); }), {root: box, rootMargin: '800px 0px'});
  pages.forEach(p => pdf.io.observe(p));
}
async function dcr_page(pdf, p) {
  const s = pdf.s, my = pdf.gen, i = +p.dataset.i;
  if (p.dataset.s === String(s)) return;
  p.dataset.s = String(s);
  try {
    const page = await pdf.doc.getPage(i + 1);
    if (my !== pdf.gen || DCR.pdf !== pdf) return;
    const vp = page.getViewport({scale: s});
    const dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(16e6 / (vp.width * vp.height)));
    const cv = document.createElement('canvas');
    cv.width = Math.floor(vp.width * dpr); cv.height = Math.floor(vp.height * dpr);
    cv.setAttribute('aria-label', tr('Page {0}', i + 1));
    await page.render({canvas: cv, canvasContext: cv.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null}).promise;
    if (my !== pdf.gen || DCR.pdf !== pdf) return;
    p.replaceChildren(cv);
  } catch { if (my === pdf.gen) p.dataset.s = ''; }
}
// Ctrl / Cmd + wheel and + / - / 0 on the preview zoom it
document.addEventListener('wheel', e => {
  const box = /** @type {any} */ (e.target).closest?.('.dc-pane .dc-rv'); if (!box || !(e.ctrlKey || e.metaKey)) return;
  e.preventDefault(); dcr_zoom(box.closest('.dc-md'), DCR.rz * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
}, {passive: false});
document.addEventListener('keydown', e => {
  const box = /** @type {any} */ (e.target).closest?.('.dc-pane .dc-rv'); if (!box || e.altKey || e.ctrlKey || e.metaKey) return;
  const md = box.closest('.dc-md'), k = e.key;
  if (k === '+' || k === '=') { e.preventDefault(); dcr_zoom(md, DCR.rz * 1.25); } else if (k === '-') { e.preventDefault(); dcr_zoom(md, DCR.rz / 1.25); } else if (k === '0') { e.preventDefault(); dcr_zoom(md, 1); }
});

// ---- the grips (drag, arrow keys, double click / Home = the standard width), kept per device
function dcr_gripMax(g, which, wrap) {  // the widest the part may get so the others keep their room
  const rem = dcr_rem(), box = which === 'props' ? $('.dc-main', wrap) : wrap;
  return Math.max(g.min * rem, (box?.clientWidth || 0) - g.keep * rem);
}
function dcr_gripSet(which, px, save) {
  const g = DCR_GRIPS[which], wrap = $('.dc-wrap'); if (!g || !wrap) return;
  if (px == null) { wrap.style.removeProperty(g.v); LS.del(g.k); }
  else {
    px = Math.round(Math.max(g.min * dcr_rem(), Math.min(dcr_gripMax(g, which, wrap), px)));
    wrap.style.setProperty(g.v, px + 'px');
    if (save) LS.set(g.k, px);
  }
  dcr_fitPv();
}
const dcr_fitPv = () => { const b = $('.dc-pane .dc-rv'); if (b) requestAnimationFrame(() => dcr_layout(b)); };
function dcr_gripNow(which) {  // the width it sets, as it stands
  const wrap = $('.dc-wrap');
  if (which === 'pane') return $('.dc-pane', wrap)?.getBoundingClientRect().width || 0;
  if (which === 'list') return $('.dc-view', wrap)?.getBoundingClientRect().width || 0;
  return $('.dc-props', wrap)?.getBoundingClientRect().width || 0;
}
document.addEventListener('pointerdown', e => {
  const gr = /** @type {any} */ (e.target).closest?.('[data-dcgrip]'); if (!gr || e.button !== 0) return;
  e.preventDefault();
  const which = gr.dataset.dcgrip;
  DCR.drag = {which, x0: e.clientX, w0: dcr_gripNow(which), px: null};
  try { gr.setPointerCapture(e.pointerId); } catch { /* a synthetic event */ }
  document.documentElement.classList.add('dc-resizing');
});
document.addEventListener('pointermove', e => {
  const d = DCR.drag; if (!d) return;
  const dx = e.clientX - d.x0;  // the list grows to the right, the pane and the properties to the left
  d.px = d.which === 'list' ? d.w0 + dx : d.w0 - dx;
  dcr_gripSet(d.which, d.px, false);
});
function dcr_dragEnd() {
  const d = DCR.drag; if (!d) return;
  DCR.drag = null; document.documentElement.classList.remove('dc-resizing');
  if (d.px != null) dcr_gripSet(d.which, d.px, true);
}
document.addEventListener('pointerup', dcr_dragEnd);
document.addEventListener('pointercancel', dcr_dragEnd);
document.addEventListener('dblclick', e => { const gr = /** @type {any} */ (e.target).closest?.('[data-dcgrip]'); if (gr) { e.preventDefault(); dcr_gripSet(gr.dataset.dcgrip, null); } });
document.addEventListener('keydown', e => {
  const gr = /** @type {any} */ (e.target).closest?.('[data-dcgrip]'); if (!gr) return;
  const which = gr.dataset.dcgrip, step = (e.shiftKey ? 4 : 1) * dcr_rem(), sign = which === 'list' ? 1 : -1;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); dcr_gripSet(which, dcr_gripNow(which) + (e.key === 'ArrowRight' ? step : -step) * sign, true); }
  else if (e.key === 'Home' || e.key === 'Delete') { e.preventDefault(); dcr_gripSet(which, null); }
});

// ---- the full screen "Show": the document in the preview of pdfview.js; the arrow keys left / right and two buttons leaf
// through the list as shown (the pane / the sheet follows), without closing it
function dcr_fullOpts(d) {
  const o = {url: dc_fileUrl(d), name: d.name, size: d.size, dlUrl: dc_fileUrl(d, true)};
  if (!dc_isPdf(d)) { o.img = /^image\//.test(d.mime || '') ? dc_fileUrl(d) : null; o.kind = o.img ? 'img' : 'file'; }
  if (isMobile()) return o;  // phones as before
  const i = dc_navIdx(d);
  if (i >= 0) {
    const n = Math.max(DC.total || 0, DC.docs.length);
    o.pos = tr('{0} of {1}', i + 1, n); o.first = i <= 0; o.last = i >= n - 1;
    o.prevT = tr('Previous document'); o.nextT = tr('Next document');
    o.step = async dir => (await dc_step(dir)) && DC.doc ? dcr_fullOpts(DC.doc) : null;
  }
  return o;
}
// true = shown here (else docs.js opens it as before)
function dcr_full(d) {
  if (typeof pdfView !== 'function') return false;
  const o = dcr_fullOpts(d);
  if (o.kind && !o.step) return false;  // an image / another file without leafing: as before (a new tab)
  pdfView(o);
  return true;
}
