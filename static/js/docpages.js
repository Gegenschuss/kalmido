// @ts-check
/* Kalmido web client: 2.777.0 B (#4874) the pages of a PDF document deleted or turned in the document view, saved as a NEW
   VERSION of its file (the original stays as the older version, the tab History). "Pages" in the preview's bar opens the
   page strip under it: every page small (drawn from the PDF the preview loaded), a tap / click marks it (Ctrl / Cmd adds,
   Shift a range), Del (or "Delete") marks the chosen pages for deletion (again = keep them), "Turn left" / "Turn right" by
   90 degrees, "Save as new version" sends it all at once. Pages the stack scan found blank carry "Blank?" (a suggestion;
   "Delete blank pages" marks them, nothing goes without Save). A receipt of the office says the original stays as a version.
   Undo is one step: the version before becomes the newest again (the file store's version path, as "Restore version",
   ablage.js ab_verStep). Server: kalmido/docs/pages.py.
   2.959.0 (#4805): reordering - a page dragged to another place (mouse: at once; finger: hold, then drag) or the chosen pages
   moved with "Move left" / "Move right" (Ctrl+Shift+arrow); the strip shows the new order, Save sends it (order). Merging
   several documents: the file store's selection bar, "More" > "Merge PDFs…" (dpm_* below, server kalmido/docs/docmerge.py).
   Classic script sharing the global scope with the others (module docs, after docview.js; docview.js asks through typeof). */
'use strict';

/** @type {{id: number|null, n: number, ver: number, blank: Set<number>, del: Set<number>, rot: Map<number, number>, sel: Set<number>, last: number, receipt: boolean, busy: boolean, cv: Map<string, HTMLCanvasElement>, io: IntersectionObserver|null, tries: number, stop: string, order: number[], drag: any, dragged: number}} */
const DPG = {id: null, n: 0, ver: 0, blank: new Set(), del: new Set(), rot: new Map(), sel: new Set(), last: -1, receipt: false, busy: false, cv: new Map(), io: null, tries: 0, stop: '', order: [], drag: null, dragged: 0};  // 2.959.0 (#4805): order = the pages (their number in the file) as shown
const DPG_TW = 72;  // the width of a small page (CSS px)

// the strip only for a document (not a plain file) that is a PDF, with the right to write (while it is recognised again the
// server counts its pages itself; a save waits for the end of the run: 409)
const dpg_on = (/** @type {any} */ d) => !!d && !d.file && d.role !== 'view' && typeof dc_isPdf === 'function' && dc_isPdf(d);
const dpg_openFor = (/** @type {any} */ d) => !!d && DPG.id === d.id;
// the button in the preview's bar (docview.js dcv_pvHtml)
function dpg_btn(/** @type {any} */ d) {
  return dpg_on(d) ? `<button type="button" class="btn sm" data-dpg="open" aria-expanded="${esc(String(dpg_openFor(d)))}" aria-controls="dv-dpg" title="${esc(tr('Delete or turn pages'))}">${ic('file', 's')} <span>${tr('Pages')}</span></button>` : '';
}
// its box between the bar and the pages; filled here (data-fl-fill: a redraw of the view keeps the content)
const dpg_boxHtml = (/** @type {any} */ d) => dpg_on(d) ? `<div class="dpg" id="dv-dpg" data-fl-fill role="region" aria-label="${esc(tr('Pages'))}"${dpg_openFor(d) ? '' : ' hidden'}></div>` : '';

function dpg_reset() {
  DPG.io?.disconnect();
  Object.assign(DPG, {id: null, n: 0, ver: 0, blank: new Set(), del: new Set(), rot: new Map(), sel: new Set(), last: -1, receipt: false, busy: false, cv: new Map(), io: null, tries: 0, stop: '', order: [], drag: null, dragged: 0});
}
const dpg_moved = () => DPG.order.some((p, i) => p !== i + 1);  // 2.959.0 (#4805)
const dpg_changed = () => DPG.del.size > 0 || [...DPG.rot.values()].some(r => r % 360) || dpg_moved();

async function dpg_open(/** @type {any} */ d) {
  if (dpg_openFor(d)) { dpg_close(); return; }
  let j; try { j = await api('GET', `/api/docs/${d.id}/pages`); } catch { return; }
  if (DC.doc?.id !== d.id || !j?.pages) return;
  dpg_reset();
  // review F7: more pages than the server changes (max) - a hint instead of a strip that could not be saved (413);
  // review F4: no right to write (a receipt of a locked month) - a hint instead of a strip whose save is refused
  const max = +j.max || 1000;
  const stop = +j.pages > max ? tr('This PDF has more than {0} pages - its pages cannot be changed here', max)
    : j.write === false ? tr('The pages of this document cannot be changed (read-only or a locked month)') : '';
  Object.assign(DPG, {id: d.id, n: stop ? 0 : +j.pages, ver: +j.version || 0, blank: new Set(stop ? [] : j.blank || []), receipt: !!j.receipt, stop});
  DPG.order = Array.from({length: DPG.n}, (_, i) => i + 1);  // 2.959.0 (#4805)
  dpg_draw(true);
}
function dpg_close() {
  const had = DPG.id; dpg_reset(); dpg_draw();
  if (had) $('.dv-view [data-dpg="open"]')?.focus();
}

function dpg_pageHtml(/** @type {number} */ p, /** @type {number} */ at = p) {
  const sel = DPG.sel.has(p), gone = DPG.del.has(p), bl = DPG.blank.has(p), r = (DPG.rot.get(p) || 0) % 360, mv = at !== p;  // 2.959.0 (#4805): at = its place now
  const lab = [tr('Page {0}', at), mv ? tr('was page {0}', p) : '', bl ? tr('looks blank') : '', gone ? tr('will be deleted') : '', r ? tr('turned by {0}°', r) : ''].filter(Boolean).join(', ');
  return `<li><button type="button" class="dpg-pg${sel ? ' on' : ''}${gone ? ' gone' : ''}${bl ? ' blank' : ''}${mv ? ' moved' : ''}" data-dpgp="${esc(String(p))}" aria-pressed="${esc(String(sel))}" aria-label="${esc(lab)}" title="${esc(lab)}" tabindex="${p === (DPG.last > 0 ? DPG.last : DPG.order[0] || 1) ? 0 : -1}">
    <span class="dpg-th" data-dpgt="${esc(String(p))}" style="--dpg-r:${esc(String(r))}deg"></span><span class="dpg-no">${esc(String(at))}${mv ? ` <small class="dpg-was">(${esc(String(p))})</small>` : ''}</span>${bl ? `<span class="dpg-bl">${tr('Blank?')}</span>` : ''}${gone ? `<span class="dpg-x">${ic('trash', 's')}</span>` : ''}</button></li>`;
}
function dpg_draw(focus = false) {
  const v = $('.dv-view'), box = v && $('.dpg', v), b = v && $('[data-dpg="open"]', v);
  b?.setAttribute('aria-expanded', String(!!DPG.id && DC.doc?.id === DPG.id));
  if (!box) return;
  if (!DPG.id || DC.doc?.id !== DPG.id) { box.hidden = true; box.textContent = ''; return; }
  box.hidden = false;
  if (DPG.stop) {
    box.innerHTML = `<p class="dpg-hint dpg-stop" role="status">${ic('info', 's')} <span>${esc(DPG.stop)}</span><button type="button" class="btn sm" data-dpg="cancel">${tr('Close')}</button></p>`;
    if (focus) $('[data-dpg="cancel"]', box)?.focus({preventScroll: true});
    return;
  }
  const fo = /** @type {any} */ (document.activeElement)?.closest?.('.dpg [data-dpgp], .dpg [data-dpg]');
  const fk = fo ? (fo.dataset.dpgp ? `[data-dpgp="${fo.dataset.dpgp}"]` : `[data-dpg="${fo.dataset.dpg}"]`) : null;
  const n = DPG.n, keep = n - DPG.del.size, s = DPG.sel.size, allGone = s > 0 && [...DPG.sel].every(p => DPG.del.has(p));
  const blankOpen = [...DPG.blank].filter(p => !DPG.del.has(p)).length;
  const ps = DPG.order.map((p, i) => dpg_pageHtml(p, i + 1));  // 2.959.0 (#4805): in the order shown
  box.innerHTML = `<div class="dpg-bar" role="toolbar" aria-label="${esc(tr('Pages'))}">
      <span class="dpg-cnt" role="status">${DPG.del.size ? esc(tr('{0} of {1} pages stay', keep, n)) : esc(trn('{0} page', '{0} pages', n))}${s ? ' · ' + esc(tr('{0} selected', s)) : ''}</span>
      <button type="button" class="btn sm" data-dpg="left"${s ? '' : ' disabled'} title="${esc(tr('Turn left'))}">${ic('undo', 's')} <span>${tr('Turn left')}</span></button>
      <button type="button" class="btn sm" data-dpg="right"${s ? '' : ' disabled'} title="${esc(tr('Turn right'))}">${ic('redo', 's')} <span>${tr('Turn right')}</span></button>
      <button type="button" class="btn sm" data-dpg="mvl"${s && s < n ? '' : ' disabled'} aria-keyshortcuts="Control+Shift+ArrowLeft" title="${esc(tr('Move the chosen pages to the left'))}">${ic('left', 's')} <span>${tr('Move left')}</span></button>
      <button type="button" class="btn sm" data-dpg="mvr"${s && s < n ? '' : ' disabled'} aria-keyshortcuts="Control+Shift+ArrowRight" title="${esc(tr('Move the chosen pages to the right'))}">${ic('right', 's')} <span>${tr('Move right')}</span></button>
      <button type="button" class="btn sm" data-dpg="del"${s && (allGone || keep - [...DPG.sel].filter(p => !DPG.del.has(p)).length >= 1) ? '' : ' disabled'} aria-keyshortcuts="Delete" title="${esc(allGone ? tr('Keep the chosen pages') : tr('Delete the chosen pages (Del)'))}">${ic(allGone ? 'check' : 'trash', 's')} <span>${allGone ? tr('Keep') : tr('Delete')}</span></button>
      <span class="spacer"></span>
      <button type="button" class="btn sm" data-dpg="cancel">${tr('Cancel')}</button>
      <button type="button" class="btn sm pri" data-dpg="save"${dpg_changed() && !DPG.busy ? '' : ' disabled'}>${tr('Save as new version')}</button></div>
    ${blankOpen ? `<p class="dpg-hint">${ic('info', 's')} <span>${esc(trn('{0} page looks blank (marked) - nothing is deleted without you', '{0} pages look blank (marked) - nothing is deleted without you', blankOpen))}</span>${keep - blankOpen >= 1 ? `<button type="button" class="linkbtn" data-dpg="blank">${tr('Delete blank pages')}</button>` : ''}</p>` : ''}
    <p class="dpg-dragnote">${esc(isMobile() ? tr('Hold a page, then drag it to its new place.') : tr('Drag a page to its new place.'))}</p>
    <ul class="dpg-list" aria-label="${esc(tr('Pages'))}">${/*html-ok*/ ps.join('')}</ul>
    <p class="dpg-note muted">${ic('info', 's')} <span>${esc(DPG.receipt ? tr('A receipt of the office: the original stays as an older version of the file (tab History).') : tr('Saving makes a new version; the original stays as an older version (tab History).'))}</span></p>`;
  dpg_thumbs(box);
  if (focus) $('[data-dpgp][tabindex="0"]', box)?.focus({preventScroll: true});
  else if (fk) $(fk, box)?.focus({preventScroll: true});
  dpg_mark();
}
// the large preview shows the pages marked for deletion faded (docview.js draws them)
function dpg_mark() {
  for (const el of $$('.dv-view .dv-pages .dv-pg[data-i]')) el.classList.toggle('dpg-gone', DPG.id === DC.doc?.id && DPG.del.has(+(el.dataset.i || 0) + 1));
}

// the small pages: drawn from the PDF the preview loaded (docview.js DVW.pdf) when they come near; a drawn one is kept
function dpg_thumbs(/** @type {any} */ box) {
  DPG.io?.disconnect(); DPG.io = null;
  const pdf = typeof DVW !== 'undefined' && DVW.pdf && !DVW.pdf.off && DVW.pdf.box?.isConnected ? DVW.pdf : null;
  for (const t of $$('[data-dpgt]', box)) { const c = DPG.cv.get(`${DPG.id}:${DPG.ver}:${t.dataset.dpgt}`); if (c) t.appendChild(c); }
  if (!pdf) {  // the preview still loads: once more a little later (while the strip is open)
    if (DPG.tries++ < 40) setTimeout(() => { const b = $('.dv-view .dpg'); if (b && !b.hidden && DPG.id) dpg_thumbs(b); }, 500);
    return;
  }
  const id = DPG.id, ver = DPG.ver;
  DPG.io = typeof IntersectionObserver === 'function' ? new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) { DPG.io?.unobserve(en.target); dpg_thumb(pdf, /** @type {any} */ (en.target), id, ver); } }), {root: $('.dpg-list', box), rootMargin: '0px 400px'}) : null;
  for (const t of $$('[data-dpgt]', box)) if (!t.firstChild) { if (DPG.io) DPG.io.observe(t); else dpg_thumb(pdf, t, id, ver); }
}
async function dpg_thumb(/** @type {any} */ pdf, /** @type {any} */ t, /** @type {any} */ id, /** @type {number} */ ver) {
  const p = +t.dataset.dpgt, k = `${id}:${ver}:${p}`;
  if (DPG.cv.has(k) || p > pdf.doc.numPages) return;
  try {
    const page = await pdf.doc.getPage(p), vp0 = page.getViewport({scale: 1}), s = DPG_TW / Math.max(vp0.width, vp0.height), vp = page.getViewport({scale: s * Math.min(window.devicePixelRatio || 1, 2)});
    const cv = document.createElement('canvas'); cv.width = Math.floor(vp.width); cv.height = Math.floor(vp.height);
    await page.render({canvas: cv, canvasContext: cv.getContext('2d'), viewport: vp}).promise;
    if (DPG.id !== id || DPG.ver !== ver || pdf.off) return;
    DPG.cv.set(k, cv);
    const now = $(`.dv-view .dpg [data-dpgt="${p}"]`); if (now && !now.firstChild) now.appendChild(cv);
  } catch { /* the number stays */ }
}

// ---- choosing, deleting, turning
function dpg_pick(/** @type {number} */ p, /** @type {any} */ e) {
  if (e.shiftKey && DPG.last > 0) { const x = DPG.order.indexOf(DPG.last), y = DPG.order.indexOf(p); for (const q of DPG.order.slice(Math.min(x, y), Math.max(x, y) + 1)) DPG.sel.add(q); }  // 2.959.0 (#4805): the range as shown
  else if (e.ctrlKey || e.metaKey) { if (DPG.sel.has(p)) DPG.sel.delete(p); else DPG.sel.add(p); }
  else if (DPG.sel.size === 1 && DPG.sel.has(p)) DPG.sel.clear();
  else { DPG.sel.clear(); DPG.sel.add(p); }
  DPG.last = p;
  dpg_draw();
  // the large preview goes to that page
  const box = $('.dv-view .dv-pages'), pg = box && $(`.dv-pg[data-i="${p - 1}"]`, box);
  if (box && pg) box.scrollTop = Math.max(0, pg.offsetTop - 8);
}
function dpg_del() {
  if (!DPG.sel.size) return;
  const all = [...DPG.sel].every(p => DPG.del.has(p));
  if (all) for (const p of DPG.sel) DPG.del.delete(p);
  else {
    const add = [...DPG.sel].filter(p => !DPG.del.has(p));
    if (DPG.n - DPG.del.size - add.length < 1) { toast(tr('At least one page must stay')); return; }
    for (const p of add) DPG.del.add(p);
  }
  dpg_draw();
}
function dpg_turn(/** @type {number} */ deg) {
  for (const p of DPG.sel) { const r = ((DPG.rot.get(p) || 0) + deg + 360) % 360; if (r) DPG.rot.set(p, r); else DPG.rot.delete(p); }
  dpg_draw();
}
function dpg_blankDel() {
  const add = [...DPG.blank].filter(p => !DPG.del.has(p));
  if (DPG.n - DPG.del.size - add.length < 1) return;
  for (const p of add) DPG.del.add(p);
  DPG.sel = new Set(add);
  dpg_draw();
}

// ---- 2.959.0 (#4805): reordering. The chosen pages one place to the left / right (as a block keeps its gaps: each moves past
// its unchosen neighbour), or the dragged page (the whole choice when it is part of it) before / after the page it is dropped on
function dpg_shift(/** @type {number} */ dir) {
  const o = DPG.order; if (!DPG.sel.size) return;
  const idx = o.map((p, i) => DPG.sel.has(p) ? i : -1).filter(i => i >= 0);
  if (dir < 0 ? idx[0] === 0 : idx[idx.length - 1] === o.length - 1) return;
  for (const i of dir < 0 ? idx : idx.reverse()) [o[i], o[i + dir]] = [o[i + dir], o[i]];
  dpg_draw(); dpg_said();
}
function dpg_moveTo(/** @type {number[]} */ ps, /** @type {number} */ to, /** @type {boolean} */ after) {
  if (ps.includes(to)) return false;
  const rest = DPG.order.filter(p => !ps.includes(p)), at = rest.indexOf(to) + (after ? 1 : 0);
  const next = [...rest.slice(0, at), ...ps, ...rest.slice(at)];
  if (next.every((p, i) => p === DPG.order[i])) return false;
  DPG.order = next; return true;
}
// the screen reader hears the new place of the (first) chosen page
const dpg_said = () => { const p = [...DPG.sel][0], st = $('.dv-view .dpg .dpg-cnt'); if (p && st) st.textContent += ' · ' + tr('Page {0}', DPG.order.indexOf(p) + 1); };
// the pointer: a mouse drags after a few pixels, a finger after holding still (DPG_HOLD ms) - a quick swipe scrolls the strip
const DPG_HOLD = 350;
function dpg_dragStart(/** @type {PointerEvent} */ e, /** @type {any} */ b) {
  if (e.button !== 0 || DPG.busy) return;
  const p = +b.dataset.dpgp, touch = e.pointerType !== 'mouse';
  const d = DPG.drag = {p, id: e.pointerId, x: e.clientX, y: e.clientY, on: false, el: b, hold: null, over: null, after: false, done: false};
  d.hold = debounce(() => { if (DPG.drag === d) dpg_dragOn(d); }, DPG_HOLD);  // the long press on a phone (core.js debounce: perf_budget)
  if (touch) d.hold();
}
function dpg_dragOn(/** @type {any} */ d) {
  d.on = true;
  d.ps = DPG.sel.has(d.p) && DPG.sel.size > 1 ? DPG.order.filter(p => DPG.sel.has(p)) : [d.p];
  for (const p of d.ps) $(`.dv-view .dpg [data-dpgp="${p}"]`)?.classList.add('dragging');
  $('.dv-view .dpg-list')?.classList.add('dpg-dragging');
  try { d.el.setPointerCapture?.(d.id); } catch { /* the page went */ }
  navigator.vibrate?.(15);
}
function dpg_dragMove(/** @type {PointerEvent} */ e) {
  const d = DPG.drag; if (!d || e.pointerId !== d.id) return;
  if (!d.on) {
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) return;
    if (e.pointerType !== 'mouse') { d.hold.cancel(); DPG.drag = null; return; }  // a finger moving at once: the strip scrolls
    dpg_dragOn(d);
  }
  e.preventDefault();
  dpg_dropAt(d, e.clientX, e.clientY);
  const ls = $('.dv-view .dpg-list');  // near an edge the strip scrolls along
  if (ls) { const r = ls.getBoundingClientRect(); if (e.clientX < r.left + 30) ls.scrollLeft -= 12; else if (e.clientX > r.right - 30) ls.scrollLeft += 12; }
}
// the page under the pointer: the drop goes before / after it (its left / right half), marked in the strip
function dpg_dropAt(/** @type {any} */ d, /** @type {number} */ x, /** @type {number} */ y) {
  for (const el of $$('.dv-view .dpg .drop-b, .dv-view .dpg .drop-a')) el.classList.remove('drop-b', 'drop-a');
  const t = /** @type {any} */ (document.elementFromPoint(x, y))?.closest?.('.dv-view .dpg [data-dpgp]');
  d.over = t && !d.ps.includes(+t.dataset.dpgp) ? +t.dataset.dpgp : null;
  if (d.over) { const r = t.getBoundingClientRect(); d.after = x > r.left + r.width / 2; t.classList.add(d.after ? 'drop-a' : 'drop-b'); }
}
function dpg_dragEnd(/** @type {PointerEvent} */ e) {
  const d = DPG.drag; if (!d || e.pointerId !== d.id) return;
  d.hold.cancel(); DPG.drag = null;
  if (!d.on) return;
  d.done = true; DPG.dragged = Date.now();  // the click that follows the drop does not choose
  $('.dv-view .dpg-list')?.classList.remove('dpg-dragging');
  if (e.type === 'pointerup' && (e.clientX || e.clientY)) dpg_dropAt(d, e.clientX, e.clientY);  // where the finger / mouse let go (a last move may not have come)
  if (e.type === 'pointerup' && d.over && dpg_moveTo(d.ps, d.over, d.after)) { DPG.sel = new Set(d.ps); DPG.last = d.ps[0]; }
  dpg_draw(); if (DPG.sel.size) dpg_said();
}
document.addEventListener('pointerdown', e => { const b = /** @type {any} */ (e.target)?.closest?.('.dv-view .dpg [data-dpgp]'); if (b) dpg_dragStart(e, b); });
document.addEventListener('pointermove', dpg_dragMove, {passive: false});
document.addEventListener('pointerup', dpg_dragEnd);
document.addEventListener('pointercancel', dpg_dragEnd);
// a finger holding a page: no scrolling of the strip while it drags, no long-press menu of the browser
document.addEventListener('touchmove', e => { if (DPG.drag?.on) e.preventDefault(); }, {passive: false});
document.addEventListener('contextmenu', e => { if (/** @type {any} */ (e.target)?.closest?.('.dv-view .dpg [data-dpgp]')) e.preventDefault(); });

// ---- saving: one request, a new version; Undo = the version before on top again (one step)
async function dpg_save() {
  const id = DPG.id, d = DC.doc; if (!id || !d || d.id !== id || DPG.busy || !dpg_changed()) return;
  const rotate = Object.fromEntries([...DPG.rot].filter(([p, r]) => r % 360 && !DPG.del.has(p)).map(([p, r]) => [String(p), r]));
  DPG.busy = true; dpg_draw();
  const order = dpg_moved() ? DPG.order.filter(p => !DPG.del.has(p)) : [];  // 2.959.0 (#4805)
  let r; try { r = await api('POST', `/api/docs/${id}/pages`, {delete: [...DPG.del].sort((a, b) => a - b), rotate, order, expect_version: DPG.ver}); } catch { DPG.busy = false; dpg_draw(); return; }
  const name = d.name, was = r?.was;
  dpg_reset(); dpg_draw();
  dpg_after(id);
  const msg = tr('Saved as version {0} with {1} - the original stays as version {2}', r.version, trn('{0} page', '{0} pages', r.pages), was);  // 2.1163.0 (#6112): 1 page
  if (!was || !r?.version) { toast(msg); return; }
  // review F1: each step names the version it expects on top (st.cur, from the answer of the step before) - a newer version
  // from elsewhere (another device, another person) is never skipped: 409, a calm hint, the step dropped
  const st = {cur: +r.version};
  offerUndo(msg, histAdd({label: tr('Pages of “{0}” changed', name), undo: () => dpg_verStep(id, was, st), redo: () => dpg_verStep(id, r.version, st)}));
}
// after a new / restored version: the file store and the open view read it again (ablage.js ab_verAfter, docview.js dcv_verAfter)
function dpg_after(/** @type {number} */ id) {
  if (typeof ab_verAfter === 'function') ab_verAfter(id);
  else if (typeof dcv_verAfter === 'function') dcv_verAfter(id);
}
async function dpg_verStep(/** @type {number} */ id, /** @type {number} */ no, /** @type {{cur: number}} */ st) {
  try {
    const j = await rawFetch('POST', `/api/files/nodes/${id}/versions/${no}/restore`, st?.cur ? {expect_version: st.cur} : undefined);
    if (st) st.cur = +j?.version || 0;
  } catch (/** @type {any} */ x) {  // histStep drops the step (thrown, already said); offline it stays
    if (x?.status === 409 && x.data?.current) toast(tr('There is a newer version by now - this step was dropped'));
    else if (x instanceof Offline) toast(tr('Offline: only works again with a connection'));
    else if (x?.message !== 'auth' && !x?.shown) toast(x?.message || tr('unknown'));
    if (x) x.shown = true;
    dpg_after(id); throw x;
  }
  dpg_after(id); return {};
}

document.addEventListener('click', e => {
  const t = /** @type {any} */ (e.target), b = t?.closest?.('.dv-view [data-dpg], .dv-view [data-dpgp]'); if (!b || !DC.doc) return;
  if (b.dataset.dpgp) { if (Date.now() - (DPG.dragged || 0) < 400) return; dpg_pick(+b.dataset.dpgp, e); return; }  // 2.959.0 (#4805): not after a drop
  const a = b.dataset.dpg;
  if (a === 'open') dpg_open(DC.doc);
  else if (a === 'cancel') dpg_close();
  else if (a === 'del') dpg_del();
  else if (a === 'left') dpg_turn(-90);
  else if (a === 'right') dpg_turn(90);
  else if (a === 'mvl') dpg_shift(-1);  // 2.959.0 (#4805)
  else if (a === 'mvr') dpg_shift(1);
  else if (a === 'blank') dpg_blankDel();
  else if (a === 'save') dpg_save();
});
// the keys inside the strip: Del / Backspace delete (or keep) the chosen pages, the arrows move along, Space / Enter choose,
// Esc closes the strip (not the view). Taken here, before the view's keys (keys.js: the window listener comes last).
document.addEventListener('keydown', e => {
  const t = /** @type {any} */ (e.target), pg = t?.closest?.('.dv-view .dpg [data-dpgp]'); if (!t?.closest?.('.dv-view .dpg') || e.altKey) return;
  const k = e.key;
  if (k === 'Escape') { dpg_close(); }
  else if (k === 'Delete' || k === 'Backspace') { if (pg && !DPG.sel.size) DPG.sel.add(+pg.dataset.dpgp); dpg_del(); }
  else if (pg && (e.ctrlKey || e.metaKey) && e.shiftKey && (k === 'ArrowLeft' || k === 'ArrowRight')) {  // 2.959.0 (#4805): move the chosen pages
    if (!DPG.sel.size) DPG.sel.add(+pg.dataset.dpgp);
    dpg_shift(k === 'ArrowRight' ? 1 : -1);
  }
  else if (pg && (k === 'ArrowLeft' || k === 'ArrowRight' || k === 'Home' || k === 'End')) {
    // 2.959.0 (#4805): along the order shown
    const o = DPG.order, i = o.indexOf(+pg.dataset.dpgp), j = k === 'Home' ? 0 : k === 'End' ? o.length - 1 : Math.max(0, Math.min(o.length - 1, i + (k === 'ArrowRight' ? 1 : -1))), to = o[j];
    // review F8: Shift marks the whole span (Shift+End / Home too), as Shift+click does
    if (e.shiftKey) { for (const q of o.slice(Math.min(i, j), Math.max(i, j) + 1)) DPG.sel.add(q); DPG.last = to; dpg_draw(); } else DPG.last = to;
    for (const x of $$('.dv-view .dpg [data-dpgp]')) x.tabIndex = +(/** @type {any} */ (x).dataset.dpgp) === to ? 0 : -1;
    /** @type {any} */ ($(`.dv-view .dpg [data-dpgp="${to}"]`))?.focus();
  } else return;
  e.preventDefault(); e.stopPropagation();
});

// ---- 2.959.0 (#4805): several PDF documents merged into one. The file store's ONE selection bar (ablage.js ab_selMoreItems /
// ab_selMenu asks dpm_selItem): "Merge PDFs…" opens a small dialog with the chosen documents in their order (drag a row, or
// "Up" / "Down"); "Merge" = POST /api/docs/merge: the pages of all become a new version of the FIRST document (its archive number,
// tags and sender stay, the original stays as an older version), the others go into the trash (restorable). One undo step for
// all of it (the server's step group, undo.js). Only PDFs; each needs the right to change it; one workspace.
const DPM = {md: /** @type {any} */ (null), xs: /** @type {{id: number, name: string}[]} */ ([]), busy: false, drag: /** @type {any} */ (null)};
const dpm_isPdf = (/** @type {any} */ x) => {
  const o = typeof ab_selObj === 'function' ? ab_selObj(x.id) : null;
  return dc_isPdf({mime: o?.mime || o?.doc?.mime || '', name: x.name || o?.name || ''});
};
function dpm_selItem(/** @type {any[]} */ docs) {
  const pdfs = (docs || []).filter(dpm_isPdf);
  if (pdfs.length < 2 || pdfs.length !== docs.length) return null;
  return {label: tr('Merge PDFs…'), icon: 'file', cls: 'msm-merge', fn: () => dpm_open(pdfs)};
}
function dpm_rows() {
  const n = DPM.xs.length;
  return DPM.xs.map((x, i) => `<li class="dpm-row" data-dpmi="${esc(String(i))}"><span class="dpm-grip" aria-hidden="true">${ic('dots', 's')}</span><span class="dpm-no">${esc(String(i + 1))}</span>
    <span class="dpm-nm">${esc(x.name)}${i === 0 ? ` <small class="muted">${esc(tr('keeps its archive number'))}</small>` : ''}</span>
    <button type="button" class="iconbtn" data-dpm="up" aria-label="${esc(tr('Up: {0}', x.name))}"${i ? '' : ' disabled'}>${ic('up', 's')}</button>
    <button type="button" class="iconbtn" data-dpm="down" aria-label="${esc(tr('Down: {0}', x.name))}"${i < n - 1 ? '' : ' disabled'}>${ic('down', 's')}</button></li>`).join('');
}
function dpm_html() {
  return `<div class="lhdr"><h3 id="dpm-h">${tr('Merge PDFs')}</h3><span class="spacer"></span><button type="button" class="iconbtn" data-dpm="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="shint">${esc(tr('The pages of all documents in this order become a new version of the first one. The others go into the trash and can be restored from there.'))}</p>
    <p class="muted dpm-drag">${esc(tr('Drag a row or use Up / Down to change the order.'))}</p>
    <ol class="dpm-list" aria-label="${esc(tr('Order'))}">${/*html-ok*/ dpm_rows()}</ol>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-dpm="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-dpm="run">${tr('Merge into one PDF')}</button></div>`;
}
function dpm_close() { const md = DPM.md; DPM.md = null; DPM.xs = []; DPM.busy = false; DPM.drag = null; if (md) md.remove(); }
function dpm_open(/** @type {any[]} */ xs) {
  dpm_close();
  DPM.xs = xs.map(x => ({id: +x.id, name: x.name || ''}));
  const md = /** @type {any} */ (modal(dpm_html()));
  md.classList.add('dpm-md'); md.setAttribute('aria-labelledby', 'dpm-h');
  DPM.md = md;
  onRemove(md, () => { if (DPM.md === md) dpm_close(); });
  md.addEventListener('click', (/** @type {any} */ e) => {
    const b = e.target.closest('[data-dpm]'); if (!b) return;
    const a = b.dataset.dpm, i = +(b.closest('[data-dpmi]')?.dataset.dpmi ?? -1);
    if (a === 'close') dpm_close();
    else if (a === 'run') dpm_run();
    else if ((a === 'up' || a === 'down') && i >= 0) dpm_swap(i, a === 'up' ? i - 1 : i + 1, a);
  });
  md.addEventListener('pointerdown', (/** @type {any} */ e) => {  // a row dragged (mouse at once, a finger from its grip)
    const r = e.target.closest('.dpm-row'); if (!r || e.button !== 0 || e.target.closest('button') || DPM.busy) return;
    if (e.pointerType !== 'mouse' && !e.target.closest('.dpm-grip')) return;
    DPM.drag = {i: +r.dataset.dpmi, id: e.pointerId, y: e.clientY, on: false};
    try { r.setPointerCapture(e.pointerId); } catch { /* gone */ }
  });
  md.addEventListener('pointermove', (/** @type {any} */ e) => {
    const d = DPM.drag; if (!d || e.pointerId !== d.id) return;
    if (!d.on && Math.abs(e.clientY - d.y) < 6) return;
    d.on = true; e.preventDefault();
    const t = /** @type {any} */ (document.elementFromPoint(e.clientX, e.clientY))?.closest?.('.dpm-row');
    for (const x of $$('.dpm-row', md)) x.classList.toggle('dpm-over', x === t && +x.dataset.dpmi !== d.i);
    $(`[data-dpmi="${d.i}"]`, md)?.classList.add('dragging');
    d.to = t ? +t.dataset.dpmi : null;
  });
  const end = (/** @type {any} */ e) => {
    const d = DPM.drag; if (!d || e.pointerId !== d.id) return;
    DPM.drag = null;
    if (d.on && e.type === 'pointerup' && d.to != null && d.to !== d.i) dpm_swap(d.i, d.to, '');
    else for (const x of $$('.dpm-row', md)) x.classList.remove('dpm-over', 'dragging');
  };
  md.addEventListener('pointerup', end); md.addEventListener('pointercancel', end);
  md.addEventListener('touchmove', (/** @type {any} */ e) => { if (DPM.drag?.on) e.preventDefault(); }, {passive: false});
  $('[data-dpm="run"]', md)?.focus({preventScroll: true});
}
// row i to place j (a drag: the row moves there; Up / Down: one step), the focus stays on the moved row's same button
function dpm_swap(/** @type {number} */ i, /** @type {number} */ j, /** @type {string} */ btn) {
  const xs = DPM.xs; if (j < 0 || j >= xs.length || i === j) return;
  const [x] = xs.splice(i, 1); xs.splice(j, 0, x);
  const ls = DPM.md && $('.dpm-list', DPM.md); if (!ls) return;
  ls.innerHTML = dpm_rows();
  if (btn) { const f = /** @type {any} */ ($(`[data-dpmi="${j}"] [data-dpm="${btn}"]`, ls)); /** @type {any} */ (f && !f.disabled ? f : $(`[data-dpmi="${j}"] button:not(:disabled)`, ls))?.focus({preventScroll: true}); }
}
async function dpm_run() {
  const md = DPM.md; if (!md || DPM.busy) return;
  const xs = DPM.xs.slice(), er = $('.aerr', md), run = /** @type {any} */ ($('[data-dpm="run"]', md));
  DPM.busy = true; if (run) run.disabled = true; if (er) er.textContent = '';
  let r; try { r = await rawFetch('POST', '/api/docs/merge', {ids: xs.map(x => x.id)}); }
  catch (x) { DPM.busy = false; if (run) run.disabled = false; if (er && DPM.md === md) er.textContent = /** @type {any} */ (x).message || tr('unknown'); return; }
  dpm_close();
  if (typeof ab_selEnd === 'function') ab_selEnd();
  if (typeof ab_relist === 'function') ab_relist();
  if (typeof ab_selDraw === 'function') ab_selDraw();
  dpg_after(xs[0].id);
  offerUndo(tr('{0} documents merged into “{1}” ({2}) - the others are in the trash', xs.length, xs[0].name, r?.pages != null ? trn('{0} page', '{0} pages', r.pages) : '?'),
    histAdd({label: tr('Merge PDFs')}));  // the server's step group (version + trash): one undo for all
}
