// @ts-check
/* Kalmido web client: 2.777.0 B (#4874) the pages of a PDF document deleted or turned in the document view, saved as a NEW
   VERSION of its file (the original stays as the older version, the tab History). "Pages" in the preview's bar opens the
   page strip under it: every page small (drawn from the PDF the preview loaded), a tap / click marks it (Ctrl / Cmd adds,
   Shift a range), Del (or "Delete") marks the chosen pages for deletion (again = keep them), "Turn left" / "Turn right" by
   90 degrees, "Save as new version" sends it all at once. Pages the stack scan found blank carry "Blank?" (a suggestion;
   "Delete blank pages" marks them, nothing goes without Save). A receipt of the office says the original stays as a version.
   Undo is one step: the version before becomes the newest again (the file store's version path, as "Restore version",
   ablage.js ab_verStep). Not here: reordering and merging (#4805). Server: kalmido/docs/pages.py.
   Classic script sharing the global scope with the others (module docs, after docview.js; docview.js asks through typeof). */
'use strict';

/** @type {{id: number|null, n: number, ver: number, blank: Set<number>, del: Set<number>, rot: Map<number, number>, sel: Set<number>, last: number, receipt: boolean, busy: boolean, cv: Map<string, HTMLCanvasElement>, io: IntersectionObserver|null, tries: number, stop: string}} */
const DPG = {id: null, n: 0, ver: 0, blank: new Set(), del: new Set(), rot: new Map(), sel: new Set(), last: -1, receipt: false, busy: false, cv: new Map(), io: null, tries: 0, stop: ''};
const DPG_TW = 72;  // the width of a small page (CSS px)

// the strip only for a document (not a plain file) that is a PDF, with the right to write (while it is recognised again the
// server counts its pages itself; a save waits for the end of the run: 409)
const dpg_on = (/** @type {any} */ d) => !!d && !d.file && d.role !== 'view' && typeof dc_isPdf === 'function' && dc_isPdf(d);
const dpg_openFor = (/** @type {any} */ d) => !!d && DPG.id === d.id;
// the button in the preview's bar (docview.js dcv_pvHtml)
function dpg_btn(/** @type {any} */ d) {
  return dpg_on(d) ? `<button type="button" class="btn sm" data-dpg="open" aria-expanded="${dpg_openFor(d)}" aria-controls="dv-dpg" title="${esc(tr('Delete or turn pages'))}">${ic('file', 's')} <span>${tr('Pages')}</span></button>` : '';
}
// its box between the bar and the pages; filled here (data-fl-fill: a redraw of the view keeps the content)
const dpg_boxHtml = (/** @type {any} */ d) => dpg_on(d) ? `<div class="dpg" id="dv-dpg" data-fl-fill role="region" aria-label="${esc(tr('Pages'))}"${dpg_openFor(d) ? '' : ' hidden'}></div>` : '';

function dpg_reset() {
  DPG.io?.disconnect();
  Object.assign(DPG, {id: null, n: 0, ver: 0, blank: new Set(), del: new Set(), rot: new Map(), sel: new Set(), last: -1, receipt: false, busy: false, cv: new Map(), io: null, tries: 0, stop: ''});
}
const dpg_changed = () => DPG.del.size > 0 || [...DPG.rot.values()].some(r => r % 360);

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
  dpg_draw(true);
}
function dpg_close() {
  const had = DPG.id; dpg_reset(); dpg_draw();
  if (had) $('.dv-view [data-dpg="open"]')?.focus();
}

function dpg_pageHtml(/** @type {number} */ p) {
  const sel = DPG.sel.has(p), gone = DPG.del.has(p), bl = DPG.blank.has(p), r = (DPG.rot.get(p) || 0) % 360;
  const lab = [tr('Page {0}', p), bl ? tr('looks blank') : '', gone ? tr('will be deleted') : '', r ? tr('turned by {0}°', r) : ''].filter(Boolean).join(', ');
  return `<li><button type="button" class="dpg-pg${sel ? ' on' : ''}${gone ? ' gone' : ''}${bl ? ' blank' : ''}" data-dpgp="${p}" aria-pressed="${sel}" aria-label="${esc(lab)}" title="${esc(lab)}" tabindex="${p === (DPG.last > 0 ? DPG.last : 1) ? 0 : -1}">
    <span class="dpg-th" data-dpgt="${p}" style="--dpg-r:${r}deg"></span><span class="dpg-no">${p}</span>${bl ? `<span class="dpg-bl">${tr('Blank?')}</span>` : ''}${gone ? `<span class="dpg-x">${ic('trash', 's')}</span>` : ''}</button></li>`;
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
  const ps = []; for (let p = 1; p <= n; p++) ps.push(dpg_pageHtml(p));
  box.innerHTML = `<div class="dpg-bar" role="toolbar" aria-label="${esc(tr('Pages'))}">
      <span class="dpg-cnt" role="status">${DPG.del.size ? esc(tr('{0} of {1} pages stay', keep, n)) : esc(trn('{0} page', '{0} pages', n))}${s ? ' · ' + esc(tr('{0} selected', s)) : ''}</span>
      <button type="button" class="btn sm" data-dpg="left"${s ? '' : ' disabled'} title="${esc(tr('Turn left'))}">${ic('undo', 's')} <span>${tr('Turn left')}</span></button>
      <button type="button" class="btn sm" data-dpg="right"${s ? '' : ' disabled'} title="${esc(tr('Turn right'))}">${ic('redo', 's')} <span>${tr('Turn right')}</span></button>
      <button type="button" class="btn sm" data-dpg="del"${s && (allGone || keep - [...DPG.sel].filter(p => !DPG.del.has(p)).length >= 1) ? '' : ' disabled'} aria-keyshortcuts="Delete" title="${esc(allGone ? tr('Keep the chosen pages') : tr('Delete the chosen pages (Del)'))}">${ic(allGone ? 'check' : 'trash', 's')} <span>${allGone ? tr('Keep') : tr('Delete')}</span></button>
      <span class="spacer"></span>
      <button type="button" class="btn sm" data-dpg="cancel">${tr('Cancel')}</button>
      <button type="button" class="btn sm pri" data-dpg="save"${dpg_changed() && !DPG.busy ? '' : ' disabled'}>${tr('Save as new version')}</button></div>
    ${blankOpen ? `<p class="dpg-hint">${ic('info', 's')} <span>${esc(trn('{0} page looks blank (marked) - nothing is deleted without you', '{0} pages look blank (marked) - nothing is deleted without you', blankOpen))}</span>${keep - blankOpen >= 1 ? `<button type="button" class="linkbtn" data-dpg="blank">${tr('Delete blank pages')}</button>` : ''}</p>` : ''}
    <ul class="dpg-list" aria-label="${esc(tr('Pages'))}">${ps.join('')}</ul>
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
  if (e.shiftKey && DPG.last > 0) { const [a, b] = DPG.last < p ? [DPG.last, p] : [p, DPG.last]; for (let i = a; i <= b; i++) DPG.sel.add(i); }
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

// ---- saving: one request, a new version; Undo = the version before on top again (one step)
async function dpg_save() {
  const id = DPG.id, d = DC.doc; if (!id || !d || d.id !== id || DPG.busy || !dpg_changed()) return;
  const rotate = Object.fromEntries([...DPG.rot].filter(([p, r]) => r % 360 && !DPG.del.has(p)).map(([p, r]) => [String(p), r]));
  DPG.busy = true; dpg_draw();
  let r; try { r = await api('POST', `/api/docs/${id}/pages`, {delete: [...DPG.del].sort((a, b) => a - b), rotate, expect_version: DPG.ver}); } catch { DPG.busy = false; dpg_draw(); return; }
  const name = d.name, was = r?.was;
  dpg_reset(); dpg_draw();
  dpg_after(id);
  const msg = tr('Saved as version {0} with {1} pages - the original stays as version {2}', r.version, r.pages, was);
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
  if (b.dataset.dpgp) { dpg_pick(+b.dataset.dpgp, e); return; }
  const a = b.dataset.dpg;
  if (a === 'open') dpg_open(DC.doc);
  else if (a === 'cancel') dpg_close();
  else if (a === 'del') dpg_del();
  else if (a === 'left') dpg_turn(-90);
  else if (a === 'right') dpg_turn(90);
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
  else if (pg && (k === 'ArrowLeft' || k === 'ArrowRight' || k === 'Home' || k === 'End')) {
    const p = +pg.dataset.dpgp, to = k === 'Home' ? 1 : k === 'End' ? DPG.n : Math.max(1, Math.min(DPG.n, p + (k === 'ArrowRight' ? 1 : -1)));
    // review F8: Shift marks the whole span (Shift+End / Home too), as Shift+click does
    if (e.shiftKey) { for (let i = Math.min(p, to); i <= Math.max(p, to); i++) DPG.sel.add(i); DPG.last = to; dpg_draw(); } else DPG.last = to;
    for (const x of $$('.dv-view .dpg [data-dpgp]')) x.tabIndex = +(/** @type {any} */ (x).dataset.dpgp) === to ? 0 : -1;
    /** @type {any} */ ($(`.dv-view .dpg [data-dpgp="${to}"]`))?.focus();
  } else return;
  e.preventDefault(); e.stopPropagation();
});
