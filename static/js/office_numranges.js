// 2.138.0 D (#2256): number ranges -- the office admin sets the next running number of every series (quotation, invoice,
// credit note, reminder, delivery note) under the number schemes of the settings, and a draft's number can be changed in the document
// editor (click on the number). Own save per row via /api/office/number-ranges (not the settings' save, hence the ids
// without "os-" and data-fg-skip); only upwards, a jump in the invoice / credit note series needs a reason (office log).
const ONUM = {ranges: null, loading: false, err: '', doc: null};
const ONUM_NAMES = {offer: N_('Quotation numbers'), invoice: N_('Invoice numbers'), credit: N_('Credit note numbers'), reminder: N_('Reminder numbers'), delivery: N_('Delivery note numbers')};
const ONUM_SCHEME_IDS = {offer: 'os-scheme', invoice: 'os-inv-scheme', credit: 'os-cr-scheme', reminder: 'os-rm-scheme', delivery: 'os-ls-scheme'};

// a number of the scheme with example values (the same building blocks the server knows, office/model.py)
function onumFmt(scheme, seq) {
  const d = new Date(), y = String(d.getFullYear()), p2 = n => String(n).padStart(2, '0');
  return String(scheme || '').replace(/\{(yyyy|yy|seq(?::0?(\d+))?|project|client|date|initials)\}/g, (m, t, w) =>
    t === 'yyyy' ? y : t === 'yy' ? y.slice(2) : t.startsWith('seq') ? String(seq).padStart(+w || 0, '0')
      : t === 'project' ? tr('Project') : t === 'client' ? tr('Client') : t === 'date' ? y + p2(d.getMonth() + 1) + p2(d.getDate()) : 'AB');
}

async function onumLoad() {
  if (ONUM.loading) return;
  ONUM.loading = true;
  try { const j = await api('GET', '/api/office/number-ranges'); ONUM.ranges = j.ranges || []; ONUM.err = ''; }
  catch (x) { ONUM.ranges = []; ONUM.err = x.message || tr('unknown'); }
  ONUM.loading = false;
  onumRedraw();
}
function onumRedraw() { const box = $('#onum-box'); if (box) box.outerHTML = onumHtml(); }

// the block of the settings page (office.js ofcSettingsHtml calls it below the number schemes); admins only
function onumHtml() {
  if (typeof ofcAdmin !== 'function' || !ofcAdmin()) return '';
  const s = OFC.info?.settings || {}, sch = k => (k === 'offer' ? s.offer_scheme : s[k + '_scheme'] || s.offer_scheme) || '';
  const sig = [OFC.info?.org_id, s.offer_counter || 'org', ...Object.keys(ONUM_NAMES).map(sch)].join('|');
  if (ONUM.sig !== sig) { ONUM.sig = sig; ONUM.ranges = null; }  // another office area / a saved scheme: read again
  if (!ONUM.ranges) { if (!ONUM.loading) setTimeout(onumLoad, 0); return `<div id="onum-box" class="onum" data-fg-skip></div>`; }
  const rows = ONUM.ranges.map(r => {
    const id = 'onum-' + r.kind, v = ONUM['v' + r.kind] ?? String(r.next), n = parseInt(v, 10), jump = n > r.min_next;
    const pv = n >= 1 ? tr('next: {0}', onumFmt(r.scheme, n)) : '';
    const hint = [tr('at least {0}', r.min_next), r.yearly ? tr('applies to {0}', r.period) : ''].filter(Boolean).join(' · ');
    return `<div class="row onumrow" data-kind="${r.kind}"><label for="${id}">${esc(tr(ONUM_NAMES[r.kind]))}</label>
      <span class="lacts"><input id="${id}" data-onum-in="${r.kind}" type="number" inputmode="numeric" min="${r.min_next}" step="1" value="${esc(v)}" class="numin" aria-describedby="${id}-h">
      <span class="muted ofcpv" id="${id}-pv" aria-live="polite">${esc(pv)}</span>
      <button type="button" class="btn sm" data-onum="set" data-kind="${r.kind}" ${n > r.next ? '' : 'disabled'}>${tr('Apply')}</button></span>
      ${r.reason_needed && jump ? `<span class="lacts onumwhy"><input id="${id}-why" data-onum-why="${r.kind}" value="${esc(ONUM['w' + r.kind] || '')}" maxlength="300" placeholder="${esc(tr('Reason for the jump (kept in the office log)'))}" aria-label="${esc(tr('Reason'))}"></span>` : ''}
      <span class="muted ofchint" id="${id}-h">${esc(hint)}</span>${ONUM['e' + r.kind] ? `<span class="ofcpv err ofchint" role="alert">${esc(ONUM['e' + r.kind])}</span>` : ''}</div>`;
  }).join('');
  return `<div id="onum-box" class="onum" data-fg-skip><h4>${tr('Next running number')}</h4>
    <p class="muted ofchint">${esc(tr('Start a series at a higher number, e.g. to continue the numbers of your previous program. Only upwards; with a year in the scheme it applies to the current year.'))}</p>
    ${ONUM.err ? `<p class="ofcpv err">${esc(ONUM.err)}</p>` : ''}${rows}</div>`;
}

async function onumApply(kind) {
  const r = (ONUM.ranges || []).find(x => x.kind === kind); if (!r) return;
  const n = parseInt($('#onum-' + kind)?.value || '', 10), why = ($('#onum-' + kind + '-why')?.value || '').trim();
  if (!(n > r.next)) return;
  if (!await askConfirm(tr('Continue {0} at {1}?', tr(ONUM_NAMES[kind]), onumFmt(r.scheme, n)),
    tr('The numbers from {0} to {1} are skipped and cannot be given later.', r.next, n - 1), {ok: tr('Apply')})) return;
  try {
    const j = await rawFetch('POST', `/api/office/number-ranges/${kind}`, {next: n, reason: why});
    Object.assign(r, j); delete ONUM['v' + kind]; delete ONUM['w' + kind]; delete ONUM['e' + kind];
    if (typeof OFC === 'object') { OFC.log = null; if (OFC.pv) delete OFC.pv[kind]; if (kind === 'offer' && OFC.info) OFC.info.number_preview = j.preview; }
    const sch = $('#' + ONUM_SCHEME_IDS[kind]); if (sch && typeof ofcSchemePv === 'function') ofcSchemePv(sch, true);  // the scheme's "next: …" again
    toast(tr('Saved'));
  } catch (x) { ONUM['e' + kind] = x.message || tr('unknown'); }
  onumRedraw();
  $('#onum-' + kind)?.focus();
}

// ---- the draft's number in the document editor (office_docs.js: the head calls onumDocHtml, a click on the number opens it)
const onumDocCan = d => !!d && !d.locked && d.can_edit && d.status === 'draft';
function onumDocHtml(d) {
  if (!onumDocCan(d)) return '';
  const e = ONUM.doc && ONUM.doc.id === d.id ? ONUM.doc : null;
  if (!e) return `<button type="button" class="btn sm onumpen" data-onum="doc-open" aria-label="${esc(tr('Change number'))}" title="${esc(tr('Change number'))}">${ic('edit', 's')}</button>`;
  const inv = d.kind !== 'offer';
  return `<span class="onumdoc" role="group" aria-label="${esc(tr('Change number'))}">
    <input id="onum-doc" value="${esc(e.val)}" maxlength="80" autocomplete="off" spellcheck="false" aria-label="${esc(tr('Change number'))}" aria-describedby="onum-doc-h">
    ${inv ? `<input id="onum-doc-why" value="${esc(e.why)}" maxlength="300" placeholder="${esc(tr('Reason (needed when numbers are skipped)'))}" aria-label="${esc(tr('Reason'))}">` : ''}
    <button type="button" class="btn sm pri" data-onum="doc-save" ${e.busy ? 'disabled' : ''}>${tr('Save')}</button><button type="button" class="btn sm" data-onum="doc-x">${tr('Cancel')}</button>
    <span class="muted ofchint" id="onum-doc-h">${esc(inv ? tr('The series continues from this number.') + (d.number_at_finalize && !d.number ? ' ' + tr('A numbered draft can no longer be deleted.') : '') : tr('The counter of the series stays as it is.'))}</span>
    ${e.err ? `<span class="ofcpv err ofchint" role="alert">${esc(e.err)}</span>` : ''}</span>`;
}
function onumDocOpen() {
  const d = typeof OFD === 'object' ? OFD.doc : null; if (!onumDocCan(d)) return;
  ONUM.doc = {id: d.id, val: d.number || '', why: '', err: '', busy: false};
  ofdDraw(); const i = $('#onum-doc'); if (i) { i.focus(); i.select(); }
}
async function onumDocSet(d, num, why) {
  const j = await rawFetch('POST', `/api/office/docs/${d.id}/number`, {number: num, reason: why});
  if (OFD.doc && OFD.doc.id === d.id) OFD.doc.number = j.number;
  if (Array.isArray(OFD.list)) { const r = OFD.list.find(x => x.id === d.id); if (r) r.number = j.number; }  // the list shows it at once
  OFD.list = null; OFD.log = null;  // ... and is read again when it opens
  return j;
}
async function onumDocSave() {
  const d = OFD.doc, e = ONUM.doc; if (!d || !e || e.busy) return;
  e.val = ($('#onum-doc')?.value || '').trim(); e.why = ($('#onum-doc-why')?.value || '').trim();
  if (e.val === (d.number || '')) { ONUM.doc = null; ofdDraw(); return; }
  e.busy = true; e.err = '';
  const old = d.number || '', kind = d.kind, id = d.id;
  try {
    const j = await onumDocSet(d, e.val, e.why);
    ONUM.doc = null;
    // one undo step where the server allows the way back: a quotation's number is free (the series is not touched);
    // invoices / credit notes / reminders never go down in their series, so no undo there
    if (kind === 'offer' && old && typeof histAdd === 'function') {
      const back = async n => { try { await onumDocSet({id}, n, ''); ofdDraw(); } catch (x) { toast(x.message || tr('unknown')); } };
      offerUndo(tr('Saved'), histAdd({label: tr('Change number'), undo: () => back(old), redo: () => back(j.number)}));
    } else toast(tr('Saved'));
  } catch (x) { e.busy = false; e.err = x.message || tr('unknown'); }
  ofdDraw();
}
// the office list follows a change made elsewhere (another device, the console, an agent): load() of the state calls this
function onumListFresh() {
  if (typeof OFD !== 'object' || typeof ofcTab !== 'function' || S.route?.mod !== 'office' || ofcTab() !== 'offers' || S.route.id || OFD.loading || !OFD.list) return;
  // 2.138.0 D (#2256, review): every state push calls this -> at most one reload per 5 s, a later push within it reloads at its end
  const wait = 5000 - (Date.now() - (onumListFresh.at || 0));
  if (wait > 0) { if (!onumListFresh.timer) onumListFresh.timer = setTimeout(() => { onumListFresh.timer = 0; onumListFresh(); }, wait); return; }
  onumListFresh.at = Date.now();
  ofdLoadList(true);
}

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-onum]');
  if (!b) { if (e.target.closest?.('.ofdhead .ofdnum b') && typeof OFD === 'object' && onumDocCan(OFD.doc) && !ONUM.doc) onumDocOpen(); return; }
  const a = b.dataset.onum;
  if (a === 'set') { e.preventDefault(); onumApply(b.dataset.kind); }
  else if (a === 'doc-open') onumDocOpen();
  else if (a === 'doc-save') onumDocSave();
  else if (a === 'doc-x') { ONUM.doc = null; ofdDraw(); }
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.dataset?.onumIn) {
    const k = t.dataset.onumIn, r = (ONUM.ranges || []).find(x => x.kind === k); if (!r) return;
    ONUM['v' + k] = t.value; delete ONUM['e' + k];
    const n = parseInt(t.value, 10), row = t.closest('.onumrow');
    const pv = $('#onum-' + k + '-pv'); if (pv) pv.textContent = n >= 1 ? tr('next: {0}', onumFmt(r.scheme, n)) : '';
    const btn = row?.querySelector('[data-onum="set"]'); if (btn) btn.disabled = !(n > r.next);
    if (r.reason_needed && (n > r.min_next) !== !!$('#onum-' + k + '-why')) { onumRedraw(); const i = $('#onum-' + k); if (i) { i.focus(); } }
  } else if (t.dataset?.onumWhy) ONUM['w' + t.dataset.onumWhy] = t.value;
  else if (t.id === 'onum-doc' && ONUM.doc) ONUM.doc.val = t.value;
  else if (t.id === 'onum-doc-why' && ONUM.doc) ONUM.doc.why = t.value;
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const t = e.target;
  if (t.dataset?.onumIn || t.dataset?.onumWhy) { e.preventDefault(); onumApply(t.dataset.onumIn || t.dataset.onumWhy); }  // never the settings' submit
  else if (t.id === 'onum-doc' || t.id === 'onum-doc-why') { e.preventDefault(); e.stopPropagation(); onumDocSave(); }
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && ONUM.doc && (e.target.id === 'onum-doc' || e.target.id === 'onum-doc-why')) { ONUM.doc = null; ofdDraw(); } });
if (typeof OA_LOG_TG === 'object') OA_LOG_TG.number_range = N_('Number ranges');  // the office log names the target
