// 2.48.0 (#1356): receipts in the document sheet (docs.js dc_mdDraw): project + category of a document, set by people;
// an agent's suggestion waits here with Accept / Reject (one undo step each: reopen). Agents never set it themselves.
const RC = {id: null, d: null, seq: 0};

function rc_slot(doc) {
  if (RC.id !== doc.id) { RC.id = doc.id; RC.d = null; RC.cb = null; rc_load(); }
  return `${rc_alsoHtml(doc)}<div class="rc-slot">${rc_html()}</div><p class="rc-cb muted" ${RC.cb?.length ? '' : 'hidden'}>${esc(rc_cbText())}</p>`;  // 2.121.0 B (#2095): + the cash book hint
}
async function rc_load() {
  const id = RC.id, seq = ++RC.seq;
  let d = null; try { d = await rawFetch('GET', `/api/docs/${id}/receipt`); } catch { d = null; }
  if (seq !== RC.seq) return;
  RC.d = d; rc_draw();
  if (d) rc_cbHint(id, seq);
}
// ---- 2.755.0 (#5236): a neighbour drawn ahead (docview.js dcv_nbDraw) gets its receipt and cash book hint filled in its own
// frames with its own data (e.rc, nothing of RC); after the snap rc_take hands them to RC, so rc_slot draws the same and loads nothing
async function rc_nbFill(e, el) {
  const id = e.d.id, sig = e.ctrl.signal;
  let d = null, cb = null; try { d = await rawFetch('GET', `/api/docs/${id}/receipt`); } catch { return; }
  if (d) { try { cb = (await rawFetch('GET', `/api/docs/${id}/cashbook`))?.entries || []; } catch { cb = []; } }
  if (sig.aborted || e.taken) return;
  e.rc = {d, cb: cb || []};
  const s = el.querySelector('.rc-slot'), c = el.querySelector('.rc-cb');
  if (s) dcv_nbSet(s, rc_html({id, d, doc: e.d}));
  if (c) { c.hidden = !e.rc.cb.length; c.textContent = rc_cbText(e.rc.cb); }
}
function rc_take(id, x) { RC.seq++; RC.id = id; RC.d = x.d; RC.cb = x.cb; }  // a request of the open one still on its way is dropped
const rc_now = id => RC.id === id && RC.d ? {d: RC.d, cb: RC.cb || []} : null;  // what the open one shows (it waits as a neighbour after a swipe); not there yet: null (loaded when taken)
// 2.121.0 B (#2095): "In the cash book no. X" under the receipt (the server answers office admins only; else an empty list)
async function rc_cbHint(id, seq) {
  let j = null; try { j = await rawFetch('GET', `/api/docs/${id}/cashbook`); } catch { j = null; }
  if (seq !== RC.seq) return;
  RC.cb = j?.entries || [];
  const el = rc_el('.rc-cb'); if (el) { el.hidden = !RC.cb.length; el.textContent = rc_cbText(); }
}
const rc_cbText = (cb = RC.cb) => (cb || []).map(e => tr('In the cash book {0} no. {1}', e.book, e.no)).join(' · ');
function rc_draw() { const el = rc_el('.rc-slot'); if (el) el.innerHTML = rc_html(); }
// 2.755.0 (#5236): the open document's slot, never the one of a neighbour drawn ahead (docview.js: .dc-nb, it may lie inside the open body mid-swipe)
const rc_el = sel => $$(sel).find(x => !x.closest('.dc-nb')) || null;
// 2.755.0 (#5236): nb = a neighbour drawn ahead ({id, d, doc}: its own receipt and document, RC stays the open one's)
function rc_html(nb) {
  const d = nb ? nb.d : RC.d; if (!d) return '';
  const r = d.receipt, w = d.can_edit;
  const sug = d.suggestions.map(s => `<div class="rc-sug" role="group" aria-label="${esc(tr('Suggestion of {0}', s.agent?.name || ''))}">
      <span><span class="muted">${esc(tr('Suggestion of {0}', s.agent?.name || tr('an agent')))}:</span> ${[s.project && `<b>${esc(s.project.name || tr('Project #{0}', s.project.id))}</b>`, s.category && `<b>${esc(s.category)}</b>`].filter(Boolean).join(' · ')}
      ${s.note ? `<br><span class="muted">${esc(s.note)}</span>` : ''}
      ${rc_money(s, w)}</span>
      ${w ? `<span class="rc-acts"><button type="button" class="btn sm" data-rc="reject:${s.id}">${tr('Reject')}</button><button type="button" class="btn sm pri" data-rc="accept:${s.id}">${tr('Accept|suggestion')}</button></span>` : ''}</div>`).join('');
  const projBtn = rc_projBtn(d, w);  // 2.540.0 (#4471): the project picker of quotations and invoices instead of a native select
  // 2.185.0 A (#2583): an e-invoice in the office's documents that is no receipt yet (read before, moved in) -> take it over
  const einv = d.einvoice_offer && w ? `<div class="rc-sug rc-einv" role="group"><span class="muted">${tr('This e-invoice is not a receipt yet.')}</span><button type="button" class="btn sm" data-rc="einv:0">${ic('receipt', 's')} ${tr('Add as receipt')}</button></div>` : '';
  // 2.497.0 A (#4046): the fields only at a receipt (a row in rc_receipts), an open suggestion, an e-invoice to take over or
  // recognised invoice values; any other document (a letter) gets the button "Record as receipt" that shows them
  // 2.522.0 (#4433): a person with an office records receipts only in the office; the private space offers "Move to office"
  const ar = rc_area(nb), wrong = rc_wrongHtml(ar);
  if (ar?.area === 'private' && !d.receipt?.is_receipt) {
    return wrong || (ar.can_move ? `<div class="rc-add"><button type="button" class="btn sm" data-rc="area:office">${ic('receipt', 's')} ${tr('Move to office')}</button></div>` : '');
  }
  if (!rc_isReceipt(d, nb) && (nb || RC.open !== RC.id)) {
    if (nb ? nb.doc.split?.stack : typeof DC !== 'undefined' && DC.doc?.id === RC.id && DC.doc.split?.stack) return wrong;  // 2.522.0 (#4468): a stack becomes no receipt
    return wrong + (w ? `<div class="rc-add"><button type="button" class="btn sm" data-rc="open:0">${ic('receipt', 's')} ${tr('Record as receipt')}</button></div>` : '');
  }
  return `${wrong}<h4 class="rc-h">${tr('Receipt')}</h4>${einv}${sug}${rc_confHtml(d)}
    <div class="row dc-f"><label for="rc-proj">${tr('Project')}</label>${projBtn}</div>
    <div class="row dc-f"><label for="rc-cat">${tr('Category')}</label><input id="rc-cat" data-rcf="category" value="${esc(r.category || '')}" maxlength="60" list="rc-cl" autocomplete="off" placeholder="${esc(tr('e.g. Travel, Material, Software'))}" ${w ? '' : 'disabled'}><datalist id="rc-cl">${d.categories.map(c => `<option value="${esc(c)}">`).join('')}</datalist></div>
    <div class="row dc-f"><label for="rc-vat">${tr('VAT rate')}</label><select id="rc-vat" data-rcf="vat" ${w ? '' : 'disabled'}><option value="">${tr('unknown')}</option>${['19', '7', '0'].map(v => `<option value="${v}" ${r.vat_pct === v ? 'selected' : ''}>${v} %</option>`).join('')}</select></div>
    <div class="row dc-f"><label for="rc-13b">${tr('Reverse charge')}</label><select id="rc-13b" data-rcf="rc13b" ${w ? '' : 'disabled'}>${[['', N_('No')], ['eu', N_('Service from a business in the EU (section 13b)')], ['other', N_('Other reverse charge (section 13b)')]].map(([v, t]) => `<option value="${v}" ${(r.rc13b || '') === v ? 'selected' : ''}>${tr(t)}</option>`).join('')}</select></div>`;  // 2.90.0 A (#1921); 2.545.0 (#4387): + reverse charge
}
// 2.540.0 (#4471): the receipt's project as a button with the project's icon and name (office_docproject.js dpj_rowHtml);
// value = the list id (empty: none). A click opens tch_listPicker over the server's set (rc_state: the area's projects without
// inbox / archive / health / budget / locked, privately only own lists): No project, the last chosen (up to 5), the rest in
// the sidebar's order with its folders, a search from 10 entries, a sheet on a phone
function rc_projBtn(d, w) {
  const p = d.receipt.project, l = p ? listById(p.id) : null;
  const cur = l ? `${listIconHtml(l, {cls: 'mlic'}) || ic('list', 's')}<span class="dpjnm">${esc(licName(l))}</span>`
    : p ? `${ic('list', 's')}<span class="dpjnm">${esc(p.name || tr('Project #{0}', p.id))}</span>` : `<span class="dpjnm muted">${tr('No project')}</span>`;
  return `<button type="button" class="btn sm dpjpick rcpick" id="rc-proj" data-rcp="pick" value="${p ? p.id : ''}" aria-haspopup="menu" ${w ? '' : 'disabled'}>${cur}${ic('down', 's dpjchev')}</button>`;
}
function rc_projPicker(b) {
  const d = RC.d; if (!d?.can_edit) return;
  const ids = new Set(d.projects.map(p => p.id)), cur = d.receipt.project?.id || 0;
  const recent = (d.recent || []).map(listById).filter(l => l && ids.has(l.id));
  const to = v => { if (v !== (cur || null)) rc_projSet(v); };
  tch_listPicker(b, {title: tr('Project'), filter: l => ids.has(l.id), on: cur, search: 10,
    pre: [{label: tr('No project'), icon: 'ban', on: !cur, fn: () => to(null)}],
    first: recent.length ? {head: tr('Recently selected'), lists: recent, rest: tr('Other projects')} : null,
    pick: l => to(l.id)});
}
async function rc_projSet(v) {
  const id = RC.id, from = rc_cur(), to = {...from, project_id: v};
  try { await rc_put(id, to); } catch { rc_draw(); return; }
  const label = tr('Changed receipt');
  histToast(label, histAdd({label, undo: () => rc_put(id, from), redo: () => rc_put(id, to)}));
}
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('.rc-slot [data-rcp="pick"]');
  if (b && RC.d) { e.preventDefault(); rc_projPicker(/** @type {HTMLElement} */ (b)); }
});
// 2.497.0 A (#4046): is the document a receipt (or about to become one)? DC.doc.extracted = what the recognition read off an
// invoice; a gross amount alone is no sign (a fee in an official letter), such a document gets the button
function rc_isReceipt(d, nb) {
  const x = nb ? nb.doc.extracted : typeof DC !== 'undefined' && DC.doc?.id === RC.id ? DC.doc.extracted : null;
  if (rc_area(nb)?.area === 'private') return !!d.receipt?.is_receipt;  // 2.522.0 (#4433): in the private space only an old receipt
  return !!(d.receipt?.is_receipt || d.suggestions?.length || d.einvoice_offer || (x && (x.net || x.vat_pct || x.invoice_no)));
}
// 2.522.0 (#4433): the area of the open document (docs/area.py ar_view: null = no office, everything as before)
const rc_area = nb => (nb ? nb.doc.area : typeof DC !== 'undefined' && DC.doc?.id === RC.id ? DC.doc.area : null) || null;  // 2.755.0 (#5236): + a neighbour's
// 2.576.0 (#4487, decision 04.11.2026): Office > Receipts and the file store apart, a document in both points to the other
// place instead of a copy: an office document (docs/area.py ar_view area 'office') lies in a folder of the file store as well
// -> "Also in: Office > Receipts" (outside the office) and "Also in: File store" (its folder); nothing for the private ones
function rc_alsoHtml(doc) {
  const ar = doc?.area; if (!ar || ar.area !== 'office') return '';
  const b = (go, name) => `<button type="button" class="linkbtn" data-rcgo="${esc(go)}">${esc(name)}</button>`;
  const ls = [S.route.mod !== 'office' && officeOn() ? b('office/receipts', tr('Office') + ' › ' + tr('Receipts')) : '',
    doc.parent_id && S.route.mod !== 'ablage' && ab_on() ? b('ablage/' + doc.parent_id, tr('File store')) : ''].filter(Boolean);
  return ls.length ? `<p class="muted rc-also">${ic('link', 's')} ${tr('Also in {0}', ls.join(' · '))}</p>` : '';
}
// "Wrong area" of a document the general input sorted (in the office: back to the private space, and the other way round)
const rc_wrongHtml = ar => ar?.wrong && ar.can_move ? `<div class="rc-sug rc-area" role="group"><span class="muted">${esc(ar.area === 'office' ? tr('Sorted into the office.') : tr('Sorted into your own documents.'))}</span><button type="button" class="btn sm" data-rc="area:${ar.area === 'office' ? 'private' : 'office'}">${ic('undo', 's')} ${tr('Wrong area')}</button></div>` : '';
// one click, one undo step: POST /api/docs/<id>/area, then the sheet and the list anew (the document may be in another workspace now)
async function rc_areaMove(id, to, b) {
  const from = to === 'office' ? 'private' : 'office';
  const go = (t, undo) => async () => {
    await api('POST', `/api/docs/${id}/area`, undo ? {to: t, undo: true} : {to: t});
    if (typeof dc_c168Refresh === 'function') await dc_c168Refresh(id);
    if (typeof dc_load === 'function' && typeof DC !== 'undefined' && DC.docs) dc_load();
    if (RC.id === id) { RC.id = null; const el = rc_el('.rc-slot'); if (el && typeof DC !== 'undefined' && DC.doc?.id === id) { el.previousElementSibling?.classList.contains('rc-also') && el.previousElementSibling.remove(); el.nextElementSibling?.classList.contains('rc-cb') && el.nextElementSibling.remove(); el.outerHTML = rc_slot(DC.doc); } }  // 2.576.0 (#4487): + the "Also in" line, no second hint
    return {};
  };
  try { await go(to, false)(); } catch { if (b) b.disabled = false; return; }
  const label = to === 'office' ? tr('Moved to office') : tr('Moved to your own documents');
  histToast(label, histAdd({label, undo: go(from, true), redo: go(to, false)}));
}
// 2.154.0 A (#1356): "Suggested by <agent>, confirmed by <person>" while the assignment is the one taken over
const rc_confHtml = d => d?.confirmed ? `<p class="muted rc-conf">${ic('check', 's')} ${esc(tr('Suggested by {0}, confirmed by {1}', d.confirmed.agent?.name || tr('an agent'), d.confirmed.by?.name || ''))}</p>` : '';
// 2.154.0 A (#1356): the office's receipt sheet (office_books.js bkSheet) shows the agents' open suggestions of a receipt
// with Accept / Reject (one undo step each) and who confirmed one; afterwards the sheet opens again with the new values
function rc_bkSlot(md, id, rc) {
  const el = $('.bk-rcs', md); if (!el) return;
  const w = rc.can_edit;
  el.innerHTML = (rc.suggestions || []).map(s => `<div class="rc-sug" role="group" aria-label="${esc(tr('Suggestion of {0}', s.agent?.name || ''))}">
      <span><span class="muted">${esc(tr('Suggestion of {0}', s.agent?.name || tr('an agent')))}:</span> ${[s.project && `<b>${esc(s.project.name || tr('Project #{0}', s.project.id))}</b>`, s.category && `<b>${esc(s.category)}</b>`,
        (s.amount || s.vat_pct) && `<b>${esc([s.amount, s.currency].filter(Boolean).join(' '))}${s.vat_pct ? ` · ${esc(s.vat_pct)} %` : ''}</b>`].filter(Boolean).join(' · ')}
      ${s.note ? `<br><span class="muted">${esc(s.note)}</span>` : ''}</span>
      ${w ? `<span class="rc-acts"><button type="button" class="btn sm" data-rcb="reject:${s.id}">${tr('Reject')}</button><button type="button" class="btn sm pri" data-rcb="accept:${s.id}">${tr('Accept|suggestion')}</button></span>` : ''}</div>`).join('') + rc_confHtml(rc);
  el.onclick = async e => {
    const b = e.target.closest('[data-rcb]'); if (!b) return;
    const [act, sid] = b.dataset.rcb.split(':');
    const again = async () => { if (typeof bkReload === 'function') bkReload(); if (md.isConnected) { md.remove(); if (typeof bkSheet === 'function') bkSheet(id); } return {}; };
    const go = a => async () => { await api('POST', `/api/receipt-suggestions/${sid}/${a}`, a === 'accept' ? {} : undefined); return again(); };
    b.disabled = true;
    try { await go(act)(); } catch { b.disabled = false; return; }
    const label = act === 'accept' ? tr('Suggestion accepted') : tr('Suggestion rejected');
    histToast(label, histAdd({label, undo: async () => { await api('POST', `/api/receipt-suggestions/${sid}/reopen`); if (typeof bkReload === 'function') bkReload(); return {}; },
      redo: async () => { await api('POST', `/api/receipt-suggestions/${sid}/${act}`, act === 'accept' ? {} : undefined); if (typeof bkReload === 'function') bkReload(); return {}; }}));
  };
}
// 2.121.0 C (#2096): amount, currency and VAT rate of a suggestion, changeable before Accept
function rc_money(s, w) {
  if (!s.amount && !s.vat_pct && !s.currency) return '';
  if (!w) return `<br><b>${esc([s.amount, s.currency].filter(Boolean).join(' '))}</b>${s.vat_pct ? ` · ${esc(s.vat_pct)} %` : ''}`;
  return `<span class="rc-money"><input inputmode="decimal" data-rcs="amount" value="${esc(s.amount || '')}" aria-label="${esc(tr('Amount'))}" placeholder="${esc(tr('Amount'))}" autocomplete="off">
    <input data-rcs="currency" value="${esc(s.currency || '')}" maxlength="3" aria-label="${esc(tr('Currency'))}" placeholder="${esc(tr('Currency'))}" autocomplete="off">
    <select data-rcs="vat_pct" aria-label="${esc(tr('VAT rate'))}"><option value="">${tr('unknown')}</option>${['19', '7', '0'].map(v => `<option value="${v}" ${s.vat_pct === v ? 'selected' : ''}>${v} %</option>`).join('')}</select></span>`;
}
function rc_accBody(b) {
  const box = b.closest('.rc-sug'), o = {};
  if (!box) return o;
  box.querySelectorAll('[data-rcs]').forEach(f => { o[f.dataset.rcs] = f.value.trim(); });
  return o;
}
const rc_cur = () => ({project_id: RC.d?.receipt?.project?.id || null, category: RC.d?.receipt?.category || '', vat_pct: RC.d?.receipt?.vat_pct ?? null, rc13b: RC.d?.receipt?.rc13b || ''});  // 2.90.0 A (#1921): + VAT rate; 2.545.0 (#4387): + reverse charge
// 2.559.0 (#4659): the slot shows the new values at once (optWrite), the server's answer replaces them; a refusal puts the
// values before back (api() said why)
function rc_putLocal(id, v) {
  return () => {
    const r = RC.id === id ? RC.d?.receipt : null; if (!r) return null;
    const old = {category: r.category, vat_pct: r.vat_pct, rc13b: r.rc13b, project: r.project};
    if ('category' in v) r.category = v.category;
    if ('vat_pct' in v) r.vat_pct = v.vat_pct == null ? null : String(v.vat_pct);
    if ('rc13b' in v) r.rc13b = v.rc13b;
    if ('project_id' in v && (v.project_id || null) !== (r.project?.id || null)) r.project = v.project_id ? (RC.d.projects || []).find(p => p.id === v.project_id) || {id: v.project_id} : null;
    return () => { if (RC.d?.receipt === r) Object.assign(r, old); };
  };
}
async function rc_put(id, v) {
  const draw = () => { if (RC.id === id) rc_draw(); };
  const j = await optWrite(rc_putLocal(id, v), () => api('PUT', `/api/docs/${id}/receipt`, v), draw, {mod: true});
  if (RC.id === id) { RC.d = j; rc_draw(); }
  return {};
}
async function rc_post(id, sid, act, body) {
  const j = await api('POST', `/api/receipt-suggestions/${sid}/${act}`, body);
  if (RC.id === id) { RC.d = j; rc_draw(); }
  return {};
}
document.addEventListener('change', async e => {
  const f = e.target.closest('.rc-slot [data-rcf]'); if (!f || !RC.d) return;
  const id = RC.id, from = rc_cur(), to = {...from};
  if (f.dataset.rcf === 'vat') to.vat_pct = f.value || null;  // 2.540.0 (#4471): the project has its own picker (rc_projPicker)
  else if (f.dataset.rcf === 'rc13b') to.rc13b = f.value;  // 2.545.0 (#4387)
  else to.category = f.value.trim();
  try { await rc_put(id, to); } catch { rc_draw(); return; }
  const label = tr('Changed receipt');
  histToast(label, histAdd({label, undo: () => rc_put(id, from), redo: () => rc_put(id, to)}));
});
document.addEventListener('click', e => {  // 2.576.0 (#4487): a jump of "Also in" closes the document's sheet (a phone, the file store)
  const b = e.target.closest?.('.rc-also [data-rcgo]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  // 2.583.0 (#4835): the document view is a page of its own (its route goes with go)
  go(b.dataset.rcgo);
}, true);
document.addEventListener('click', async e => {
  const b = e.target.closest('.rc-slot [data-rc]'); if (!b) return;
  const [act, sid] = b.dataset.rc.split(':'), id = RC.id;
  b.disabled = true;
  if (act === 'einv') { rc_einvTake(id, b); return; }
  if (act === 'area') { rc_areaMove(id, sid, b); return; }  // 2.522.0 (#4433): "Move to office" / "Wrong area"
  if (act === 'open') { RC.open = id; rc_draw(); $('#rc-proj')?.focus(); return; }  // 2.497.0 A (#4046): show the receipt fields
  const body = act === 'accept' ? rc_accBody(b) : undefined;
  try { await rc_post(id, +sid, act, body); } catch { b.disabled = false; return; }
  const label = act === 'accept' ? tr('Suggestion accepted') : tr('Suggestion rejected');
  histToast(label, histAdd({label, undo: () => rc_post(id, +sid, 'reopen'), redo: () => rc_post(id, +sid, act, body)}));
});
// 2.185.0 A (#2583): "Add as receipt" -- one undo step (all empty = no receipt again)
async function rc_einvTake(id, b) {
  const take = async () => { const j = await api('POST', `/api/docs/${id}/receipt/einvoice`); if (RC.id === id) { RC.d = j; rc_draw(); } return {}; };
  try { await take(); } catch { b.disabled = false; return; }
  const label = tr('Added as receipt');
  histToast(label, histAdd({label, undo: () => rc_put(id, {project_id: null, category: '', vat_pct: null}), redo: take}));
}
// 2.121.0 A (#2092): what the recognition read off a receipt (supplier, number, net, VAT rate, gross) -- one line
// "Recognised: ..." with Take over / Discard while it would change something (doc.extracted.new); Take over and Discard are
// one undo step each. The invoice number stays visible (copy button) even after the take-over.
function rx_html(d) {
  // 2.522.0 (#4468): a stack waiting for the decision: one line instead of values / hints mixed from several letters (the server
  // sends none of them, kalmido/docs/web.py); no reading with an agent either
  if (d?.split?.stack) return `<div class="rx-slot"><p class="muted rx-stack" role="note">${esc(tr('Amounts and numbers are recognised per letter after splitting.'))}</p></div>`;
  const ag = typeof rcr_html === 'function' ? rcr_html(d) : '';  // 2.299.0 E (#3194): read by an agent / "Read with an agent" (asstprop.js)
  if (!d?.extracted && !d?.duplicate_of && !d?.checks && !ag) return '';  // 2.299.0 D (#3193): + the hints of the check
  const x = d.extracted || {};  // 2.146.0 B (#2452): a possible duplicate shows without recognised values too
  const w = d.role !== 'view', cur = x.currency || d.currency;
  const parts = [x.supplier && `<b>${esc(x.supplier)}</b>`, x.invoice_no && esc(tr('No. {0}', x.invoice_no)),
    x.net && `${tr('net')} ${esc(dc_money(x.net, cur))}`, x.vat_pct && esc(tr('VAT {0} %', x.vat_pct)), x.gross && `${tr('gross')} ${esc(dc_money(x.gross, cur))}`].filter(Boolean);
  const line = w && !x.hidden && x.new?.length && parts.length ? `<div class="rx-sug" role="group" aria-label="${esc(tr('Recognised'))}">
    <span><span class="muted">${tr('Recognised')}:</span> ${parts.join(' · ')}</span>
    <span class="rc-acts"><button type="button" class="btn sm" data-rx="dismiss:${d.id}">${tr('Discard')}</button><button type="button" class="btn sm pri" data-rx="apply:${d.id}">${tr('Apply')}</button></span></div>` : '';
  const no = x.invoice_no ? `<div class="rx-no"><span class="muted">${tr('Invoice number')}:</span> <span class="rx-nov">${esc(x.invoice_no)}</span>
    <button type="button" class="linkbtn" data-rx="copy:${d.id}" aria-label="${esc(tr('Copy'))}">${tr('Copy')}</button></div>` : '';
  // 2.146.0 B (#2452): an older document looks like the same invoice -- a link to it, "No duplicate" keeps the decision
  const du = d.duplicate_of, dup = du ? `<div class="rx-dup" role="note">${ic('alert', 's')}<span>${tr('Possibly a duplicate of')} <a href="#docs/${+du.id}">${esc(du.name)}</a></span>
    ${w ? `<button type="button" class="btn sm" data-rx="nodup:${d.id}">${tr('No duplicate')}</button>` : ''}</div>` : '';
  const ck = rck_html(d);  // 2.299.0 D (#3193)
  return line || no || dup || ag || ck ? `<div class="rx-slot">${dup}${ag}${line}${no}${ck}</div>` : '';
}
// 2.299.0 D (#3193): the hints of the fixed check of a receipt (required details, net + VAT = gross, rate, VAT ID) -- folded
// below the recognised values, never blocking; "Hide hints" hides the ones shown now (one undo step), a new one shows again
function rck_html(d) {
  const k = d?.checks;
  if (!k?.items?.length) return '';
  // 2.892.0 (#5453): only real gaps count; "not found in the text" (soft) is listed below them, never shown on its own
  const real = k.items.filter(x => !x.soft), soft = k.items.filter(x => x.soft);
  if (!real.length) return '';
  const w = d.role !== 'view', n = real.length;
  if (k.hidden) return w ? `<div class="rck rck-off"><span class="muted">${esc(trn('{0} hint hidden', '{0} hints hidden', n))}</span>
    <button type="button" class="linkbtn" data-rck="show:${d.id}">${tr('Show')}</button></div>` : '';
  const warn = real.some(x => x.level === 'warn');
  return `<details class="rck${warn ? ' rck-warn' : ''}"><summary>${ic('alert', 's')}<span>${esc(trn('{0} hint on this receipt', '{0} hints on this receipt', n))}</span></summary>
    <ul class="rck-list">${real.map(x => `<li class="${x.level === 'warn' ? 'rck-w' : 'rck-h'}">${esc(x.text)}</li>`).join('')}${soft.map(x => `<li class="rck-h rck-s">${esc(x.text)}</li>`).join('')}</ul>
    ${w ? `<button type="button" class="btn sm ghost" data-rck="hide:${d.id}">${tr('Hide hints')}</button>` : ''}</details>`;
}
async function rck_post(id, act) {
  const j = await api('POST', `/api/docs/${id}/checks`, {do: act});
  if (typeof DC === 'object' && DC.doc?.id === id && j.doc) { DC.doc = j.doc; dc_mdDraw($('.dc-md')); dc_load(); }
  if (typeof bkRxAfter === 'function') bkRxAfter(id);
  if (typeof rclReload === 'function') rclReload();
  return j;
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-rck]'); if (!b) return;
  const [act, sid] = b.dataset.rck.split(':'), id = +sid;
  b.disabled = true;
  try { await rck_post(id, act); } catch { b.disabled = false; return; }
  const back = act === 'hide' ? 'show' : 'hide', label = act === 'hide' ? tr('Hints hidden') : tr('Hints shown');
  histToast(label, histAdd({label, undo: () => rck_post(id, back), redo: () => rck_post(id, act)}));
});
async function rx_post(id, b) {
  const j = await api('POST', `/api/docs/${id}/extracted`, b);
  if (typeof DC === 'object' && DC.doc?.id === id && j.doc) { DC.doc = j.doc; dc_mdDraw($('.dc-md')); dc_load(); }
  if (RC.id === id) rc_load();
  if (typeof bkRxAfter === 'function') bkRxAfter(id);
  return j;
}
// 2.525.0 (#4281): data-rx means something else elsewhere too (agents.js reaction picker: the reaction key, orgexport.js
// retention box: its kind) - only the receipt actions with a document id count here (one-meaning guard: data-rx)
const RX_ACTS = new Set(['copy', 'dismiss', 'apply', 'nodup']);
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-rx]'); if (!b) return;
  const [act, sid] = b.dataset.rx.split(':'), id = +sid;
  if (!RX_ACTS.has(act) || !(id > 0)) return;
  if (act === 'copy') {
    const v = b.closest('.rx-no')?.querySelector('.rx-nov')?.textContent || '';
    try { await navigator.clipboard.writeText(v); toast(tr('Copied')); } catch { toast(tr('Copying is blocked in this browser')); }
    return;
  }
  b.disabled = true;
  let j; try { j = await rx_post(id, {do: act}); } catch { b.disabled = false; return; }
  if (act === 'nodup') {
    const label = tr('Marked as no duplicate');
    histToast(label, histAdd({label, undo: () => rx_post(id, {do: 'dup'}), redo: () => rx_post(id, {do: 'nodup'})}));
  } else if (act === 'apply') {
    const before = j.before, label = tr('Recognised values applied');
    histToast(label, histAdd({label, undo: () => rx_post(id, {do: 'restore', before}), redo: () => rx_post(id, {do: 'apply'})}));
  } else {
    const label = tr('Suggestion discarded');
    histToast(label, histAdd({label, undo: () => rx_post(id, {do: 'show'}), redo: () => rx_post(id, {do: 'dismiss'})}));
  }
});
