// @ts-check
/* Kalmido web client: "Optimise PDF" (2.892.0, #4873, includes #4806). A scanned PDF becomes smaller and searchable (a text
   layer): the result is a NEW VERSION of its file, the original stays as the older version (tab History; "Download original").
   (1) The action in the document view's "Actions" (docview.js dcv_actItems asks po_actItems): the dialog with the level
   (Automatic / Black and white / Greyscale), the switch "Remove blank pages" (on in Automatic) and, measured first in the
   background, the list of the pages that would go; then "Optimise" and the sizes before / after ("2.4 MB → 160 KB"), or "not
   smaller - the file stays as it is". An office receipt: only this button, with the hint that the original stays.
   (2) The file store's ONE selection bar (ablage.js ab_selMoreItems asks po_selItem): the chosen documents with one level, the
   result per document in the dialog. (3) Settings > Documents: "Optimise new scans automatically" (docs.js dc_sDraw asks
   po_setHtml). (4) #4806: an optimised document offers "Download searchable PDF" and "Download original" in its actions.
   Server: kalmido/docs/pdfoptq.py (routes, queue), kalmido/docs/pdfopt.py (the tools). Module docs (lazyload.js), classic
   script sharing the global scope with the others. */
'use strict';

// timer: a generation number, not a timeout id -- a newer poll (or closing) makes the waiting one do nothing (no clearTimeout: perf budget)
const PO = {md: null, d: null, ids: null, j: null, timer: 0, busy: false, mode: 'auto', blankSet: false};
const PO_LEVELS = [['auto', N_('Automatic'), N_('Pages of text in black and white, pages with colour or photos stay in colour or grey')],
  ['bw', N_('Black and white'), N_('Every page in black and white: the smallest file')], ['gray', N_('Greyscale'), N_('Every page in grey')]];
const PO_RUNS = ['check', 'scan', 'wait', 'run'];
const po_size = n => typeof fmtSize === 'function' ? fmtSize(+n || 0) : `${+n || 0} B`;
const po_fromTo = j => `${po_size(j.before)} → ${po_size(j.after)}`;

// ---- (1) the document view's actions: optimise, and the two downloads of an optimised document (#4806)
// 2.1011.0 (#5688): entries of the shared menu (the downloads per fn, no link in a menu)
function po_actItems(d, w) {
  const p = d?.pdfopt; if (!p || d.file) return [];
  const out = [];
  if (w && p.can) out.push({label: tr('Optimise PDF…'), icon: 'file', act: 'po-open', fn: () => po_open(d)});
  if (p.orig) out.push({label: tr('Download searchable PDF'), icon: 'download', act: 'po-dlsearch', fn: () => dcv_dlGo(`/api/docs/${+d.id}/file?dl=1`)},
    {label: tr('Download original'), icon: 'download', act: 'po-dlorig', fn: () => dcv_dlGo(`/api/files/nodes/${+d.id}/content?v=${+p.orig}&dl=1`)});
  return out;
}

function po_dlgHtml(many) {
  const office = !many && PO.d?.pdfopt?.office;
  return `<div class="lhdr"><h3 id="po-h">${tr('Optimise PDF')}</h3><span class="spacer"></span><button type="button" class="iconbtn" data-po="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="shint">${esc(many ? trn('{0} document selected', '{0} documents selected', many) + ' · ' : '')}${esc(tr('Makes a scan smaller and searchable (a text layer). The result is a new version; the original stays as the older version in the history and can be restored.'))}</p>
    ${office ? `<p class="po-office muted" role="note">${ic('info', 's')} ${esc(tr('A receipt of the office: it is never optimised automatically. The original stays unchanged as the older version.'))}</p>` : ''}
    ${many ? `<p class="po-office muted" role="note">${ic('info', 's')} ${esc(tr('Receipts of the office among them keep their original unchanged as the older version.'))}</p>` : '' /* review F5 */}
    <fieldset class="po-lv"><legend>${tr('Level')}</legend>${PO_LEVELS.map(([v, l, h]) => `<label class="chkl"><input type="radio" name="po-lv" value="${esc(v)}" ${PO.mode === v ? 'checked' : ''}> <span><b>${esc(tr(l))}</b> <span class="muted">${esc(tr(h))}</span></span></label>`).join('<br>')}</fieldset>
    ${many ? '' : `<label class="chkl"><input type="checkbox" data-po="blank" ${PO.mode === 'auto' ? 'checked' : ''}> ${tr('Remove blank pages')}</label>`}
    <p class="po-pages muted" role="status" aria-live="polite">${many ? esc(tr('With several documents no page is removed: blank pages go on a single document, after the list of them.')) : ''}</p>
    <div class="po-res" role="status" aria-live="polite"></div>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-po="close">${tr('Close')}</button><button type="button" class="btn pri" data-po="run">${tr('Optimise')}</button></div>`;
}
const po_blankOn = () => !!$('[data-po="blank"]', PO.md)?.checked;
const po_pageList = ns => ns.map(n => tr('Page {0}', n)).join(', ');
function po_close() { PO.timer++; const md = PO.md; PO.md = null; PO.d = null; PO.ids = null; PO.j = null; md?.remove(); }

async function po_open(d) {
  if (!d?.id) return;
  po_close();
  Object.assign(PO, {d, ids: null, j: null, busy: false, mode: 'auto', blankSet: false});
  const md = /** @type {any} */ (modal(po_dlgHtml(0)));
  md.classList.add('po-md'); md.setAttribute('aria-labelledby', 'po-h');
  PO.md = md;
  po_bind(md);
  onRemove(md, () => { if (PO.md === md) po_close(); });
  // the pages are measured in the background first (blank pages, colour); a measure of the current version is used again
  let j; try { j = await api('GET', `/api/docs/${d.id}/pdfopt`); } catch { return; }
  if (PO.md !== md) return;
  if (j.state === 'ready' && j.fresh || PO_RUNS.includes(j.state)) po_show(j); else po_post({check: 1});
}
function po_bind(md) {
  md.addEventListener('click', e => {
    const b = /** @type {any} */ (e.target).closest('[data-po]'); if (!b) return;
    if (b.dataset.po === 'close') po_close();
    else if (b.dataset.po === 'run') { if (PO.ids) po_runMany(); else po_post({}); }
  });
  md.addEventListener('change', e => {
    const t = /** @type {any} */ (e.target);
    if (t.name === 'po-lv') { PO.mode = t.value; const bl = $('[data-po="blank"]', md); if (bl && !PO.blankSet) bl.checked = PO.mode === 'auto'; if (PO.j) po_show(PO.j); }
    else if (t.dataset?.po === 'blank') { PO.blankSet = true; if (PO.j) po_show(PO.j); }
  });
}
async function po_post(extra) {
  const md = PO.md, d = PO.d; if (!md || !d) return;
  const er = $('.aerr', md); if (er) er.textContent = '';
  try {
    const j = await rawFetch('POST', `/api/docs/${d.id}/pdfopt`, {mode: PO.mode, blank: po_blankOn(), ...extra});
    if (PO.md === md) po_show(j);
  } catch (x) { if (PO.md === md && er) er.textContent = /** @type {any} */ (x).message || tr('unknown'); }
}
// the dialog follows the state of the server until it is done (GET .../pdfopt; a real state, no fixed wait)
function po_show(j) {
  const md = PO.md; if (!md) return;
  PO.j = j;
  const pg = $('.po-pages', md), res = $('.po-res', md), run = $('[data-po="run"]', md);
  const running = PO_RUNS.includes(j.state);
  if (run) run.disabled = running;
  if (pg) {
    if (j.state === 'check' || j.state === 'scan') pg.textContent = tr('Checking the pages…');
    else if (Array.isArray(j.pages) && j.fresh) {
      const blank = j.pages.map((p, i) => p.b ? i + 1 : 0).filter(Boolean), go = po_blankOn() && blank.length < j.pages.length ? blank : [];
      const k = {bw: 0, gray: 0, color: 0}; for (const p of j.pages) if (k[p.k] != null) k[p.k]++;
      const kinds = PO.mode === 'auto' ? /** @type {[number, string][]} */ ([[k.bw, N_('{0} black and white')], [k.gray, N_('{0} grey')], [k.color, N_('{0} in colour')]]).filter(x => x[0]).map(([n, t]) => tr(t, n)).join(', ') : '';
      pg.innerHTML = `${esc(trn('{0} page', '{0} pages', j.pages.length))}${kinds ? ` · ${esc(kinds)}` : ''}<br><span class="po-drop">${go.length ? esc(tr('Pages that go: {0}', po_pageList(go))) : po_blankOn() ? esc(tr('No blank pages found.')) : ''}</span>`;
    }
  }
  if (res) {
    if (j.state === 'wait' || j.state === 'run') res.innerHTML = `<p>${esc(tr('Optimising… this can take a minute per page.'))}</p>`;
    else if (j.state === 'done' && j.fresh) res.innerHTML = `<p class="po-size"><b>${esc(po_fromTo(j))}</b></p><p class="muted">${esc(tr('Saved as a new version. The original stays in the history.'))}${j.drop?.length ? ' ' + esc(tr('Removed: {0}', po_pageList(j.drop))) : ''}</p>`;
    else if (j.state === 'same' && j.fresh) res.innerHTML = `<p class="po-size po-same"><b>${esc(po_fromTo(j))}</b></p><p class="muted">${esc(tr('Not smaller: the file stays as it is, no new version.'))}</p>`;
    else if (j.state === 'failed' || j.state === 'skipped') res.innerHTML = `<p class="po-fail">${esc(j.error_text || tr('Optimising failed.'))}</p>`;
    else res.innerHTML = '';
  }
  if (j.state === 'done' && run) { run.hidden = true; const d = PO.d; if (d && typeof dcv_verAfter === 'function') dcv_verAfter(d.id); }
  const g = ++PO.timer;
  if (running) { const d = PO.d; setTimeout(async () => { if (PO.timer !== g || PO.md !== md || !d) return; let n; try { n = await api('GET', `/api/docs/${d.id}/pdfopt`); } catch { return; } if (PO.md === md) po_show(n); }, 1500); }
}

// ---- (2) the selection bar's "More": the chosen documents, the result per document
function po_selItem(docs) {
  if (!docs?.length) return null;
  return {label: tr('Optimise PDF…'), icon: 'file', cls: 'msm-pdfopt', fn: () => po_openMany(docs)};
}
function po_openMany(docs) {
  po_close();
  Object.assign(PO, {d: null, ids: docs.map(x => ({id: x.id, name: x.name || ''})), j: null, mode: 'auto', blankSet: false});
  const md = /** @type {any} */ (modal(po_dlgHtml(docs.length)));
  md.classList.add('po-md'); md.setAttribute('aria-labelledby', 'po-h');
  PO.md = md;
  po_bind(md);
  onRemove(md, () => { if (PO.md === md) po_close(); });
}
async function po_runMany() {
  const md = PO.md, xs = PO.ids; if (!md || !xs) return;
  const er = $('.aerr', md), run = $('[data-po="run"]', md); if (er) er.textContent = '';
  let r; try { r = await rawFetch('POST', '/api/docs/pdfopt', {ids: xs.map(x => x.id), mode: PO.mode, blank: po_blankOn()}); } catch (x) { if (er) er.textContent = /** @type {any} */ (x).message || tr('unknown'); return; }
  if (PO.md !== md) return;
  if (run) run.hidden = true;
  const q = new Set(r.queued || []), rows = xs.filter(x => q.has(x.id));
  const res = $('.po-res', md);
  if (res) res.innerHTML = `${r.skipped ? `<p class="muted">${esc(tr('{0} skipped', r.skipped))} · ${esc(tr('Only scanned PDFs you may change'))}</p>` : ''}<ul class="po-list">${rows.map(x => `<li data-poid="${esc(x.id)}"><b>${esc(x.name)}</b> · <span class="po-st">${esc(tr('Waiting…'))}</span></li>`).join('')}</ul>`;
  po_pollMany(md, rows.map(x => x.id));
}
async function po_pollMany(md, ids) {
  const open = [];
  for (const id of ids) {
    let j; try { j = await api('GET', `/api/docs/${id}/pdfopt`); } catch { continue; }
    if (PO.md !== md) return;
    const st = $(`[data-poid="${id}"] .po-st`, md); if (!st) continue;
    if (PO_RUNS.includes(j.state)) { open.push(id); st.textContent = j.state === 'run' ? tr('Optimising…') : tr('Waiting…'); }
    else if (j.state === 'done') st.textContent = po_fromTo(j) + (j.drop?.length ? ' · ' + tr('Removed: {0}', po_pageList(j.drop)) : '');
    else if (j.state === 'same') st.textContent = po_fromTo(j) + ' · ' + tr('Not smaller: the file stays as it is, no new version.');
    else st.textContent = j.error_text || tr('Optimising failed.');
  }
  const g = ++PO.timer;
  if (open.length && PO.md === md) setTimeout(() => { if (PO.timer === g) po_pollMany(md, open); }, 2000);
  else if (PO.md === md && typeof ab_relist === 'function') ab_relist();
}

// ---- (3) Settings > Documents: optimise new scans automatically (never the office's receipts)
const po_setHtml = (s, dis) => `<label class="chkl po-auto"><input type="checkbox" data-po="setauto" ${s.pdf_opt_auto ? 'checked' : ''} ${/*html-ok*/ dis}> ${tr('Optimise new scans automatically')}</label>
  <p class="muted">${esc(tr('New scanned PDFs get a smaller new version with a text layer (level Automatic, no page is removed). Receipts of the office never.'))}</p>`;
document.addEventListener('change', async e => {
  const t = /** @type {any} */ (e.target); if (t?.dataset?.po !== 'setauto' || typeof DC === 'undefined' || !DC.set) return;
  const s = DC.set, on = !!t.checked;
  try { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, pdf_opt_auto: on}); toast(tr('Saved')); } catch { t.checked = !on; }
});

