// @ts-check
/* Kalmido web client: tables, 2.578.0 (#3462) -- the print view as a PDF. "Print / PDF…" in a table's menu opens a small
   dialog: portrait or landscape, fit to the page width, the header row on every page, page numbers, the whole sheet (the rows
   your filters show) or the selected cells. The server writes the PDF from the values you see (POST
   /api/sheets/<id>/print.pdf, sheets/shprint.py); it opens in the app's PDF view, where it is printed or downloaded.
   The quick browser print of 2.124.0 (sheetkinds.js shk_print) stays one click away in the dialog. Loaded with the tables
   module (lazyload.js LD_MODS.sheets), never at the start. */
const SHP = {last: /** @type {Record<string, any>} */ ({orient: 'portrait', fit: true, head: true, numbers: true})};

function shp_sel(sh) {  // the selected rectangle as row / column ids, or null (no selection or a single cell)
  if (typeof shvRect !== 'function' || !SHV.anc || !SHV.cur || (SHV.anc.r === SHV.cur.r && SHV.anc.c === SHV.cur.c)) return null;
  const q = shvRect(); if (!q) return null;
  const [rs, cs] = shvGrid();
  return {rows: rs.slice(q.r0, q.r1 + 1), cols: cs.slice(q.c0, q.c1 + 1)};
}
async function shp_make(sh, o) {  // the PDF's bytes (throws with the server's message)
  const r = await fetch(`/api/sheets/${sh.id}/print.pdf`, {method: 'POST', credentials: 'same-origin',
    headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/json'}, body: JSON.stringify(o)});
  if (!r.ok) {
    const j = await r.json().catch(() => null);
    throw new Error(j?.error?.message || j?.message || (typeof j?.error === 'string' ? j.error : '') || httpErrText(r.status));
  }
  return new Uint8Array(await r.arrayBuffer());
}
function shp_dialog(sh) {
  if (!sh) return;
  // 2.693.0 (#5148): a pivot sheet has no cells, rows or selection: the server prints its computed table (with the total)
  const pv = sh.kind === 'pivot', sel = pv ? null : shp_sel(sh), vis = pv ? [] : shvVisRows(sh), last = SHP.last;
  const chk = (k, label) => `<label class="chkl"><input type="checkbox" data-shp="${k}" ${last[k] ? 'checked' : ''}> ${label}</label>`;
  const md = modal(`<h3>${tr('Print / PDF')}</h3>
    <fieldset class="shp-set"><legend>${tr('Page')}</legend>
      <label class="chkl"><input type="radio" name="shp-o" value="portrait" ${last.orient !== 'landscape' ? 'checked' : ''}> ${tr('Portrait')}</label>
      <label class="chkl"><input type="radio" name="shp-o" value="landscape" ${last.orient === 'landscape' ? 'checked' : ''}> ${tr('Landscape')}</label></fieldset>
    ${pv ? '' : `<fieldset class="shp-set"><legend>${tr('Print')}</legend>
      <label class="chkl"><input type="radio" name="shp-w" value="all" ${sel ? '' : 'checked'}> ${tr('Whole sheet')}${vis.length < sh.rows.length ? ` <small class="muted">${esc(tr('{0} of {1} rows shown', vis.length, sh.rows.length))}</small>` : ''}</label>
      <label class="chkl"><input type="radio" name="shp-w" value="sel" ${sel ? 'checked' : 'disabled'}> ${sel ? esc(tr('Selection ({0} × {1} cells)', sel.rows.length, sel.cols.length)) : tr('Selection')}</label>
      ${sel ? '' : `<small class="muted shp-hint">${tr('Select cells in the table first to print only them.')}</small>`}</fieldset>`}
    <fieldset class="shp-set shp-opts"><legend>${tr('Options')}</legend>${chk('fit', tr('Fit to page width'))}${chk('head', tr('Repeat the header row on every page'))}${chk('numbers', tr('Page numbers'))}</fieldset>
    <p class="muted mhint" id="shp-err" role="alert"></p>
    <div class="foot">${pv ? '' : `<button type="button" class="btn ghost" data-m="quick" title="${esc(tr('The browser prints the shown rows directly'))}">${ic('printer', 's')}${tr('Browser print')}</button>`}<span class="spacer"></span>
      <button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="pdf">${ic('pdf', 's')}${tr('Show PDF')}</button></div>`);
  md.classList.add('shpmd');
  md.addEventListener('click', async e => {
    const b = e.target instanceof Element ? /** @type {HTMLButtonElement|null} */ (e.target.closest('button[data-m]')) : null; if (!b) return;
    const a = b.dataset.m;
    if (a === 'close') { md.remove(); return; }
    if (a === 'quick') { md.remove(); shk_print(); return; }
    if (a !== 'pdf') return;
    const val = (/** @type {string} */ q) => (/** @type {HTMLInputElement|null} */ (md.querySelector(q)))?.value;
    const on = (/** @type {string} */ k) => !!(/** @type {HTMLInputElement|null} */ (md.querySelector(`input[data-shp="${k}"]`)))?.checked;
    const o = {orient: val('input[name="shp-o"]:checked') === 'landscape' ? 'landscape' : 'portrait', fit: on('fit'), head: on('head'), numbers: on('numbers')};
    SHP.last = {...o};
    const pick = pv ? {rows: null, cols: null} : val('input[name="shp-w"]:checked') === 'sel' && sel ? sel : {rows: vis.length < sh.rows.length ? vis.map(r => r.id) : null, cols: null};
    const err = md.querySelector('#shp-err');
    b.disabled = true;
    let data;
    try { data = await shp_make(sh, {...o, ...pick}); } catch (x) { b.disabled = false; if (err) err.textContent = /** @type {any} */ (x).message; return; }
    md.remove();
    const name = (sh.title || tr('Table')).replace(/[\\/:*?"<>|]+/g, ' ').trim() + '.pdf';
    let url = '';
    try { url = URL.createObjectURL(new Blob([data], {type: 'application/pdf'})); } catch (x) { /* no blob addresses: the view shows the bytes */ }
    try { await loadModule('pdf'); } catch (x) { /* offline: the download below still works */ }
    if (typeof pdfView === 'function') pdfView({url, name, dlUrl: url, data, size: data.length});
    else if (url) window.open(url, '_blank', 'noopener');
  });
}
