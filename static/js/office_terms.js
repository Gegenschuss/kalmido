// @ts-check
/* Kalmido web client: 2.113.2 (#2253) the office's terms and conditions (AGB) as a PDF per language.
   Settings: one row per language (file name, "as of" date, view / replace / remove for the office's admin; members only
   see and view). Removing is one undo step (restore of the stored state). The send dialog of office_docs.js asks
   agbSendRow for its tick "Attach terms and conditions" (only shown when the document's language has terms).
   Classic script sharing the global scope with the others (lazy module "office", after office.js / office_docs.js). */
'use strict';

const AGB = {data: null, loading: false, ws: null};
const AGB_LANGS = [['de', 'Deutsch'], ['en', 'English']];

async function agbLoad(force) {
  if (AGB.loading || (AGB.data && !force && AGB.ws === OFC.ws)) return;
  AGB.loading = true;
  try { AGB.data = await api('GET', '/api/office/terms'); AGB.ws = OFC.ws; }
  catch { AGB.data = {terms: {}, admin: false, failed: true}; AGB.ws = OFC.ws; }
  AGB.loading = false;
  agbRedraw();
}
function agbRedraw() {
  const box = $('#agb-box'); if (box) box.outerHTML = agbSettingsHtml();
}
const agbFileUrl = (lg, inline) => `/api/office/terms/${lg}/file${inline && !/; wv\)/.test(navigator.userAgent || '') ? '?inline=1' : ''}`;
function agbRowHtml(lg, name, t, adm) {
  const info = t ? [t.name, tr('as of {0}', fmtDateLoc(t.date))].filter(Boolean).join(' · ') : tr('No terms and conditions yet');
  const acts = t ? `<a class="btn sm" href="${agbFileUrl(lg, true)}" target="_blank" rel="noopener">${tr('Show')}</a>`
    + (adm ? `<button type="button" class="btn sm" data-agb="up" data-lg="${lg}">${tr('Replace')}</button><button type="button" class="btn sm" data-agb="del" data-lg="${lg}">${tr('Remove')}</button>` : '')
    : (adm ? `<button type="button" class="btn sm" data-agb="up" data-lg="${lg}">${ic('upload', 's')}<span>${tr('Upload')}</span></button>` : '');
  return `<li class="agbrow" data-lg="${lg}"><span class="ofcn"><b>${esc(name)}</b><small class="muted">${esc(info)}</small></span>${acts ? `<span class="lacts">${acts}</span>` : ''}</li>`;
}
// the block in the office settings (next to the logo); loads once per workspace
function agbSettingsHtml() {
  if (!AGB.data || AGB.ws !== OFC.ws) { setTimeout(() => agbLoad(), 0); return `<div class="row" id="agb-box"><label>${tr('Terms and conditions (PDF)')}</label><span class="muted">${tr('Loading…')}</span></div>`; }
  const t = AGB.data.terms || {}, adm = !!AGB.data.admin;
  return `<div class="row" id="agb-box"><label>${tr('Terms and conditions (PDF)')}</label><ul class="ofclist agblist" role="list">${AGB_LANGS.map(([lg, n]) => agbRowHtml(lg, n, t[lg], adm)).join('')}</ul>
    <span class="muted ofchint">${esc(tr('Sent along with quotations in the same language; the quotation names the date. At most {0} MB.', AGB.data.max_mb || 10))}</span></div>`;
}
function agbUploadDialog(lg) {
  const cur = AGB.data?.terms?.[lg], today = ds(new Date());
  if (typeof loadCss === 'function') loadCss('calendar').catch(() => {});  // the app's own date picker
  const lname = (AGB_LANGS.find(x => x[0] === lg) || [lg, lg])[1];
  ofdDlg(cur ? tr('Replace terms and conditions ({0})', lname) : tr('Upload terms and conditions ({0})', lname),
    ofdF('agb-file', tr('PDF file'), `<input type="file" id="ofd-agb-file" accept="application/pdf,.pdf">`)
    + ofdF('agb-date', tr('As of'), dateIn('ofd-agb-date', today, {label: tr('As of'), clear: false}))
    + `<p class="muted ofchint">${tr('Quotations already finalised keep the terms they were made with.')}</p>`,
    cur ? tr('Replace') : tr('Upload'), async md => {
      const f = $('#ofd-agb-file', md)?.files?.[0];
      if (!f) throw new Error(tr('No file'));
      const fd = new FormData(); fd.append('file', f); fd.append('date', $('#ofd-agb-date', md)?.value || '');
      try { AGB.data = await rawFetch('POST', `/api/office/terms/${lg}`, fd); }
      catch (x) { throw new Error(typeof ofcUpErr === 'function' ? ofcUpErr(x) : (x.message || tr('unknown'))); }
      AGB.ws = OFC.ws; agbRedraw(); toast(tr('Saved'));
    });
}
async function agbDelete(lg) {
  let j;
  try { j = await api('DELETE', `/api/office/terms/${lg}`); } catch (x) { toast(x.message || tr('unknown')); return; }
  AGB.data = j; agbRedraw();
  const old = j.removed;
  offerUndo(tr('Removed'), histAdd({label: tr('Terms and conditions removed'),
    undo: async () => { AGB.data = await api('POST', `/api/office/terms/${lg}/restore`, old); agbRedraw(); },
    redo: async () => { AGB.data = await api('DELETE', `/api/office/terms/${lg}`); agbRedraw(); }}));
}
// the send dialog (office_docs.js ofdSendDialog): tm = GET /api/office/docs/<id>/terms
function agbSendRow(tm, smtp) {
  if (!tm?.terms) return '';
  return `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="ofd-s-terms" ${tm.default ? 'checked' : ''} ${smtp ? '' : 'disabled'}> ${tr('Attach terms and conditions')} <span class="muted">(${esc(tr('as of {0}', fmtDateLoc(tm.terms.date)))})</span></label></div>`;
}
// the history of a document: "sent by e-mail (with terms and conditions as of ...)"
const agbLogNote = x => x?.action === 'send' && x.detail?.terms?.date ? ` <span class="muted">(${esc(tr('with terms and conditions as of {0}', fmtDateLoc(x.detail.terms.date)))})</span>` : '';

document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-agb]'); if (!b) return;
  e.preventDefault();
  if (b.dataset.agb === 'up') agbUploadDialog(b.dataset.lg);
  else if (b.dataset.agb === 'del') agbDelete(b.dataset.lg);
});
