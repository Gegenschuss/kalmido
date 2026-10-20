// @ts-check
/* Kalmido web client: 2.112.1 A (#2058) the phone scan -- photograph pages with the camera (on a computer: choose pictures),
   order them, turn them, and save them as ONE PDF in the file store (or, from the documents, as a document). The server
   builds the PDF (kalmido/files/bulk.py: orientation, size, black and white); the pictures are made smaller here first so a
   phone sends less. Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const ABM_SCAN_PAGES = 30, ABM_SCAN_EDGE = 2400;
const abm_objUrl = b => { try { return URL.createObjectURL(b); } catch { return ''; } };  // no preview where the browser has none
const abm_objFree = u => { try { if (u) URL.revokeObjectURL(u); } catch { /* nothing to free */ } };
const abm_two = n => String(n).padStart(2, '0');
const abm_scanName = () => { const d = new Date(); return `Scan ${d.getFullYear()}-${abm_two(d.getMonth() + 1)}-${abm_two(d.getDate())} ${abm_two(d.getHours())}-${abm_two(d.getMinutes())}`; };
// a picture as a JPEG with the long edge at most ABM_SCAN_EDGE (the browser applies the camera's orientation); the file as it
// is when the browser cannot draw it (the server reads it then)
async function abm_shrink(f) {
  try {
    const bm = await window.createImageBitmap(f);
    const k = Math.min(1, ABM_SCAN_EDGE / Math.max(bm.width, bm.height));
    const cv = document.createElement('canvas'); cv.width = Math.round(bm.width * k); cv.height = Math.round(bm.height * k);
    cv.getContext('2d').drawImage(bm, 0, 0, cv.width, cv.height); bm.close?.();
    const b = await new Promise(res => cv.toBlob(res, 'image/jpeg', 0.85));
    return b && b.size ? b : f;
  } catch { return f; }
}
// o = {parent: folder id | null, space: the space at the top, docs: true = file it as a document (docs.js), done(items)}
function abm_scanOpen(o = {}) {
  const pages = [];  // {blob, url, rot}
  $('.abscandlg')?.remove();
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${ic('camera')} ${tr('Scan')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="abscpages" id="abs-pages" role="list" aria-label="${esc(tr('Pages'))}"></div>
    <label class="btn pri abscshot">${ic('camera', 's')} <span>${tr('Take a page')}</span><input type="file" id="abs-file" accept="image/*" capture="environment" multiple hidden></label>
    <label class="absclbl"><span>${tr('Name')}</span><input type="text" id="abs-name" maxlength="150" value="${esc(abm_scanName())}"></label>
    <label class="chkl absclbl"><input type="checkbox" id="abs-bw" checked> ${tr('Black and white (document)')}</label>
    <div class="foot"><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><span class="spacer"></span><button type="button" class="btn pri" data-abs="save" disabled>${ic('pdf', 's')} ${tr('Save as PDF')}</button></div>`);
  md.classList.add('abscandlg');
  const close = modalGuard(md, () => pages.length > 0);
  const free = () => pages.forEach(p => abm_objFree(p.url));
  onRemove(md, free);
  const draw = () => {
    const box = $('#abs-pages', md); if (!box) return;
    box.innerHTML = pages.length ? pages.map((p, i) => `<div class="abscpg" role="listitem" data-pg="${i}"><span class="abscimg">${p.url ? `<img src="${p.url}" alt="${esc(tr('Page {0}', i + 1))}" style="transform:rotate(${p.rot}deg)">` : ic('picture')}</span>
      <span class="abscno">${esc(tr('Page {0}', i + 1))}</span><span class="abscacts">
      <button type="button" class="iconbtn" data-abp="up" ${i ? '' : 'disabled'} aria-label="${esc(tr('Move page {0} up', i + 1))}" title="${esc(tr('Move up'))}">${ic('up', 's')}</button>
      <button type="button" class="iconbtn" data-abp="down" ${i < pages.length - 1 ? '' : 'disabled'} aria-label="${esc(tr('Move page {0} down', i + 1))}" title="${esc(tr('Move down'))}">${ic('down', 's')}</button>
      <button type="button" class="iconbtn" data-abp="rot" aria-label="${esc(tr('Turn page {0}', i + 1))}" title="${esc(tr('Turn by 90 degrees'))}">${ic('redo', 's')}</button>
      <button type="button" class="iconbtn" data-abp="del" aria-label="${esc(tr('Remove page {0}', i + 1))}" title="${esc(tr('Remove'))}">${ic('trash', 's')}</button></span></div>`).join('')
      : `<div class="muted abscempty">${tr('Photograph the first page. Each further photo becomes the next page of the PDF.')}</div>`;
    const sv = $('[data-abs="save"]', md); if (sv) sv.disabled = !pages.length;
    const sh = $('.abscshot span', md); if (sh) sh.textContent = pages.length ? tr('Next page') : tr('Take a page');
  };
  draw();
  md.addEventListener('change', async e => {
    if (/** @type {any} */ (e.target).id !== 'abs-file') return;
    const fs = [...(/** @type {any} */ (e.target).files || [])].filter(f => /^image\//.test(f.type) || !f.type); /** @type {any} */ (e.target).value = '';
    for (const f of fs) {
      if (pages.length >= ABM_SCAN_PAGES) { toast(tr('At most {0} pages per scan', ABM_SCAN_PAGES)); break; }
      const blob = await abm_shrink(f);
      pages.push({blob, url: abm_objUrl(blob), rot: 0});
    }
    draw();
  });
  md.addEventListener('click', async e => {
    if (/** @type {any} */ (e.target).closest('[data-m="close"]')) { close(); return; }
    const b = /** @type {any} */ (e.target).closest('[data-abp]');
    if (b) {
      const i = +b.closest('[data-pg]').dataset.pg, a = b.dataset.abp;
      if (a === 'up' && i > 0) pages.splice(i - 1, 0, pages.splice(i, 1)[0]);
      else if (a === 'down' && i < pages.length - 1) pages.splice(i + 1, 0, pages.splice(i, 1)[0]);
      else if (a === 'rot') pages[i].rot = (pages[i].rot + 90) % 360;
      else if (a === 'del') abm_objFree(pages.splice(i, 1)[0].url);
      draw();
      $(`[data-pg="${Math.min(i, pages.length - 1)}"] [data-abp="${a}"]`, md)?.focus();
      return;
    }
    const sv = /** @type {any} */ (e.target).closest('[data-abs="save"]'); if (!sv || !pages.length) return;
    const fd = new FormData();
    pages.forEach((p, i) => { fd.append('page', p.blob, `page-${i + 1}.jpg`); fd.append('rot', String(p.rot)); });
    const name = ($('#abs-name', md).value || '').trim() || abm_scanName();
    fd.append('name', name); fd.append('bw', $('#abs-bw', md).checked ? '1' : '0');
    if (o.docs) fd.append('out', 'pdf');
    else if (o.parent) fd.append('parent_id', String(o.parent)); else fd.append('space', o.space || 'private');
    sv.disabled = true; sv.classList.add('busy');
    try {
      if (o.docs) {  // the PDF comes back and goes through the documents' own upload (recognition, undo there)
        const r = await fetch('/api/files/scan', {method: 'POST', body: fd, headers: {'X-Requested-With': 'kalmido'}});
        if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || tr('Error {0}', r.status)); }
        const pdf = new File([await r.blob()], /\.pdf$/i.test(name) ? name : name + '.pdf', {type: 'application/pdf'});
        md.remove(); o.done?.(await dc_upload([pdf]));
        return;
      }
      const j = await api('POST', '/api/files/scan', fd);
      md.remove(); o.done?.(j.items || []);
    } catch (x) {
      if (o.docs && x?.message) toast(x.message);  // api() shows its own errors
      sv.disabled = false; sv.classList.remove('busy');
    }
  });
  return md;
}
