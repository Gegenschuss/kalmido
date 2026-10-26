// 2.120.0 E (#2091): the own letterhead of the office documents -- a section of the office settings: upload a PDF
// (page 1 = first page, page 2 = following pages), preview, margins of page 1 / following pages, switches for the own
// head and footer. Saved at once on every change (no save button), every change is one step of the undo history.
const BPL = {st: null, oid: null, busy: false};
const BPL_SIDES = [['top', N_('Top')], ['right', N_('Right')], ['bottom', N_('Bottom')], ['left', N_('Left')]];

async function bp_load() {
  try { const j = await api('GET', '/api/office/letterhead'); BPL.st = j.letterhead; } catch { BPL.st = BPL.st || {on: false}; }
  bp_draw();
}
function bp_draw() { const el = $('#bpset'); if (el) el.outerHTML = bp_settingsHtml(OFC.info?.settings || {}, ofcAdmin() ? '' : 'disabled'); }

function bp_marginsHtml(key, label, vals, dis) {
  return `<fieldset class="bpm" style="border:0;padding:0;margin:0 0 .75rem" ${dis}><legend style="padding:0;margin-bottom:.25rem">${esc(label)}</legend><div style="display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center">${BPL_SIDES.map(([s, n], i) => `<span style="display:inline-flex;gap:.4rem;align-items:center"><label class="muted" for="bp-${key}-${s}">${esc(tr(n))}</label><input id="bp-${key}-${s}" class="numin" style="width:4.5rem" inputmode="decimal" data-bp="${key}" data-i="${i}" value="${esc(fmtNum(vals?.[i] ?? 0, 1))}" aria-label="${esc(label + ': ' + tr(n) + ' (mm)')}" ${dis}></span>`).join('')}<span class="muted">mm</span></div></fieldset>`;
}
function bp_settingsHtml(s, dis) {
  if (BPL.oid !== OFC.info?.org_id) { BPL.oid = OFC.info?.org_id; BPL.st = null; setTimeout(bp_load, 0); }
  const st = BPL.st, adm = !dis;
  if (!st) return `<section class="bpset" id="bpset" data-fg-skip aria-labelledby="bp-h"><h3 id="bp-h">${tr('Letterhead')}</h3><p class="muted">${tr('Loading…')}</p></section>`;
  const pages = st.pages === 1 ? tr('one page for all pages') : tr('page 1 for the first page, page 2 for the following pages');
  const file = st.on ? `<span>${ic('file', 's')} ${esc(st.name || tr('Letterhead'))} <span class="muted">· ${esc(pages)}</span></span>` : `<span class="muted">${tr('No letterhead yet')}</span>`;
  const up = adm ? `<input type="file" id="bp-file" accept="application/pdf,.pdf" hidden><button type="button" class="btn sm" data-bp-act="pick" ${BPL.busy ? 'disabled' : ''}>${ic('upload', 's')} ${st.on ? tr('Replace') : tr('Upload PDF')}</button>` : '';
  return `<section class="bpset" id="bpset" data-fg-skip aria-labelledby="bp-h"><h3 id="bp-h">${tr('Letterhead')}</h3><div class="shint">${tr('A PDF behind every quotation, invoice, credit note and reminder: its page 1 behind the first page, its page 2 behind the following pages (a one-page PDF behind all).')}</div>
    <p class="muted ofchint">${tr('PDF, A4 portrait, up to 10 MB')}</p>
    <div class="row"><span class="lacts">${file}</span></div>
    ${st.on && st.pdfa_hint ? `<p class="dtp-warn" role="status">${esc(st.pdfa_hint)}</p>` : ''}
    <div class="lacts" style="margin-bottom:.5rem">${up}<button type="button" class="btn sm" data-bp-act="preview">${ic('eye', 's')} ${tr('Preview')}</button>${adm && st.on ? `<button type="button" class="btn sm" data-bp-act="del">${ic('trash', 's')} ${tr('Remove')}</button>` : ''}</div>
    ${st.on ? `<fieldset class="bpf" style="border:0;padding:0;margin:0" ${dis}>${ofcChk('bp-hide-head', tr('Leave out our own head (logo, company name, fold marks)'), st.hide_head)}
    ${ofcChk('bp-hide-foot', tr('Leave out our own footer (number and page stay)'), st.hide_footer)}
    <p class="muted ofchint">${tr('Margins in mm. Page 1: “top” is where the address field begins (DIN 5008: 45 mm).')}</p>
    ${bp_marginsHtml('m1', tr('Page 1'), st.m1, dis)}${bp_marginsHtml('m2', tr('Following pages'), st.m2, dis)}</fieldset>
    <span class="aerr" id="bp-err" role="alert"></span>` : ''}</section>`;
}

// one step of the undo history (toast, Ctrl+Z, the undo / redo buttons)
const bp_hist = (msg, undo, redo) => offerUndo(msg, histAdd({label: tr('Letterhead'), undo, redo}));
const bp_send = async (m, u, b) => { const j = await api(m, u, b); BPL.st = j.letterhead; bp_draw(); return j; };
async function bp_put(b, undoBody) {
  const err = $('#bp-err'); if (err) err.textContent = '';
  try { await bp_send('PUT', '/api/office/letterhead', b); }
  catch (x) { if (err) err.textContent = x.message || ''; else toast(x.message || tr('unknown')); return; }
  bp_hist(tr('Saved'), () => bp_send('PUT', '/api/office/letterhead', undoBody), () => bp_send('PUT', '/api/office/letterhead', b));
}
async function bp_upload(file) {
  if (!file) return;
  const before = BPL.st?.on ? BPL.st.file : '';
  BPL.busy = true; bp_draw();
  try {
    const j = await ofcUpload('/api/office/letterhead', file); BPL.st = j.letterhead;
    const now = j.letterhead.file;  // undo: the letterhead before (or none); redo: this one again
    bp_hist(tr('Letterhead saved'), () => bp_send('POST', '/api/office/letterhead/restore', {file: before}), () => bp_send('POST', '/api/office/letterhead/restore', {file: now}));
  } catch (x) { toast(ofcUpErr(x)); }
  BPL.busy = false; bp_draw();
}
async function bp_act(a) {
  if (a === 'pick') { const inp = $('#bp-file'); if (inp) { inp.onchange = () => { bp_upload(inp.files[0]); inp.value = ''; }; inp.click(); } }
  else if (a === 'preview') {
    const u = '/api/office/letterhead/preview?v=' + Date.now();
    typeof pdfView === 'function' ? pdfView({url: u, name: tr('Letterhead') + '.pdf', dlUrl: u}) : window.open(u, '_blank', 'noopener');
  } else if (a === 'del') {
    const was = BPL.st?.file || '';
    try { await bp_send('DELETE', '/api/office/letterhead'); bp_hist(tr('Removed'), () => bp_send('POST', '/api/office/letterhead/restore', {file: was}), () => bp_send('DELETE', '/api/office/letterhead')); }
    catch (x) { toast(x.message || tr('unknown')); }
  }
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-bp-act]'); if (!b || !b.closest('#bpset')) return; e.preventDefault(); bp_act(b.dataset.bpAct); });
document.addEventListener('change', e => {
  const t = e.target; if (!t.closest?.('#bpset') || !BPL.st) return;
  if (t.id === 'bp-hide-head' || t.id === 'bp-hide-foot') {
    const k = t.id === 'bp-hide-head' ? 'hide_head' : 'hide_footer';
    bp_put({[k]: t.checked ? 1 : 0}, {[k]: BPL.st[k] ? 1 : 0});
  } else if (t.dataset.bp) {
    const k = t.dataset.bp, vals = [...(BPL.st[k] || [])], i = +t.dataset.i, v = parseFloat(String(t.value).trim().replace(',', '.'));
    if (!Number.isFinite(v)) { t.value = fmtNum(vals[i] ?? 0, 1); return; }
    const old = [...vals]; vals[i] = v;
    bp_put({[k]: vals}, {[k]: old});
  }
});
document.addEventListener('keydown', e => {  // Enter in a margin field saves it, never the settings form's submit
  const x = e.target; if (e.key !== 'Enter' || e.isComposing || !x.dataset?.bp || !x.closest?.('#bpset')) return;
  e.preventDefault(); e.stopPropagation(); x.blur();
}, true);
