// @ts-check
// 2.119.0 A (#2288): entertainment receipts (Bewirtungsbelege) in the office, built like the travel expenses
// (office_travel.js): the list with the filters of the travel expenses (year, person = host or guest, occasion), the
// mask (place, host and guests from choice lists, amounts per VAT rate, tip, the restaurant bill), approving = locking
// (the host's digital confirmation; new places and people join the choice lists), undoing the approval (logged), the PDF
// receipt, the evaluation 70 / 30 (CSV / PDF) and the choice lists in the office settings. Admins of the office only.
// Server: kalmido/office/meals.py.
const BW = {data: null, loading: false, err: null, year: String(new Date().getFullYear()), person: '', personName: '', occ: '', view: 'list', rep: null, oid: undefined};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, /** @type {any} */ (['meals', 'meal', N_('Entertainment receipts'), 1, () => bw_html(), 'money']));  // admins only, menu group Money
const BW_U = '/api/office/meals';
const bw_reload = () => { BW.data = null; BW.rep = null; ofcDraw(); };
const bw_meal = id => (BW.data?.meals || []).find(m => m.id === id);
const bw_amt = n => ofcMoney(n);
const bw_ppl = m => [m.host, ...(m.guests || [])].filter(p => p && p.name);
const bw_pn = p => p.name + (p.extra ? ` (${p.extra})` : '');
const bw_title = m => m.place_name || tr('Entertainment receipt');
function bw_persons() {  // the people of the office + host / guests of the loaded meals (+ the chosen one), by name
  const m = new Map((BW.data?.people || []).map(p => [rk_pkey(p), p.name]));
  for (const x of BW.data?.meals || []) for (const p of bw_ppl(x)) if (!m.has(rk_pkey(p))) m.set(rk_pkey(p), p.name);
  if (BW.person && !m.has(BW.person)) m.set(BW.person, BW.personName || BW.person.replace(/^[un]:?/, ''));
  return [...m].sort((a, b) => a[1].localeCompare(b[1], LOCALE()));
}
const bw_q = () => (BW.year ? `year=${BW.year}` : '') + (BW.person ? `&person=${encodeURIComponent(BW.person)}` : '') + (BW.occ ? `&occasion=${encodeURIComponent(BW.occ)}` : '');
function bw_shown() {
  const o = BW.occ.trim().toLocaleLowerCase();
  return (BW.data?.meals || []).filter(m => (!BW.person || bw_ppl(m).some(p => rk_pkey(p) === BW.person)) && (!o || (m.occasion || '').toLocaleLowerCase().includes(o)));
}
async function bw_load() {
  if (BW.loading) return;
  BW.loading = true;
  try { BW.data = await api('GET', BW_U + (BW.year ? `?year=${BW.year}` : '')); BW.err = null; }
  catch (x) { BW.data = null; BW.err = x.message || tr('unknown'); }
  BW.loading = false;
  ofcDraw();
}

// ---- the tab
function bw_html() {
  if (BW.oid !== OFC.info?.org_id) Object.assign(BW, {oid: OFC.info?.org_id, data: null, rep: null, err: null, person: '', occ: ''});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see entertainment receipts.')}</div>`;
  if (BW.err) return `<div class="empty">${esc(BW.err)}</div>`;
  if (!BW.data) { if (!BW.loading) setTimeout(bw_load, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const y0 = new Date().getFullYear(), years = [y0 + 1, y0, y0 - 1, y0 - 2, y0 - 3].map(String);
  const ps = bw_persons();
  const views = `<div class="seg" role="group" aria-label="${esc(tr('View'))}">${[['list', tr('Receipts')], ['report', tr('Evaluation')]].map(([k, n]) => `<button type="button" data-bw="view" data-v="${k}" class="${BW.view === k ? 'on' : ''}" aria-pressed="${BW.view === k}">${n}</button>`).join('')}</div>`;
  const bar = `<div class="ofcbar rkbar bwbar"><select id="bw-year" aria-label="${esc(tr('Year'))}"><option value="">${tr('All years')}</option>${years.map(y => `<option ${y === BW.year ? 'selected' : ''}>${y}</option>`).join('')}</select>
    ${ps.length > 1 ? `<select id="bw-person" class="rkperson" aria-label="${esc(tr('Person'))}"><option value="">${esc(tr('All people'))}</option>${ps.map(([k, n]) => `<option value="${esc(k)}" ${k === BW.person ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>` : ''}
    <input type="search" id="bw-occf" class="bwocc" value="${esc(BW.occ)}" placeholder="${esc(tr('Occasion'))}" aria-label="${esc(tr('Filter by occasion'))}" autocomplete="off" enterkeyhint="search">
    ${views}<span class="spacer"></span><button class="btn sm pri" data-bw="new">${ic('plus', 's')}<span>${tr('New receipt')}</span></button></div>`;
  return bar + (BW.view === 'report' ? bw_reportHtml() : bw_listHtml());
}
const bw_tag = m => m.locked ? `<span class="rotag bwok">${ic('lock', 's')}<span>${esc(tr('Approved'))}</span></span>` : `<span class="rotag bwdraft">${esc(tr('Draft'))}</span>`;
function bw_listHtml() {
  const ms = bw_shown();
  if (!ms.length) return (BW.data.meals || []).length ? `<div class="empty nempty">${tr('No entertainment receipts for this filter.')}</div>`
    : `<div class="empty nempty eact">${ic('meal')}<span>${tr('No entertainment receipts yet. Add the first one after a business meal.')}</span></div>`;
  return `<ul class="ofclist rklist bwlist" role="list">${ms.map(m => `<li><button type="button" class="ofcrow" data-bw="open" data-id="${m.id}"><span class="ofcn"><b>${esc(bw_title(m))}</b>
    <small class="muted">${esc([fmtDateLoc(m.date), m.occasion, bw_ppl(m).map(p => p.name).join(', ')].filter(Boolean).join(' · '))}</small></span>
    ${bw_tag(m)}<span class="rksum">${bw_amt(m.calc.gross)}</span></button>${bw_rowBtn(m)}</li>`).join('')}</ul>`;
}
const bw_rowBtn = m => `<button type="button" class="iconbtn ofdrmore rkmore" data-bw="rowmore" data-id="${m.id}" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('chev', 's')}</button>`;
const bw_pdfUrl = m => `${BW_U}/${m.id}/pdf`;
function bw_openPdf(m) {  // the receipt in the app's PDF viewer (like the other office PDFs), else a new tab
  const a = document.createElement('a');
  a.href = bw_pdfUrl(m) + '?inline=1'; a.target = '_blank'; a.rel = 'noopener';
  a.setAttribute('data-pview', JSON.stringify({url: bw_pdfUrl(m) + '?inline=1', name: `${m.date} ${bw_title(m)}.pdf`, dlUrl: bw_pdfUrl(m)}));
  a.hidden = true; document.body.appendChild(a); a.click(); a.remove();
}
function bw_rowMenu(id, anchor) {
  const m = bw_meal(+id); if (!m) return;
  const can = ofcAdmin(), label = bw_title(m);
  menu(anchor, [
    {label: tr('Open'), icon: 'eye', fn: () => bw_modal(m)},
    {label: 'PDF', icon: 'pdf', fn: () => bw_openPdf(m)},
    can ? {label: tr('Duplicate'), icon: 'copy', fn: () => bw_dup(m)} : null,
    can && !m.locked && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? {label: tr('Move to another workspace…'), icon: 'brief',
      fn: () => ofm_move({what: 'meals', ids: [m.id], from: ofm_officeFrom(), label: qn(label), after: async () => bw_reload()})} : null,
    can && m.locked ? {label: tr('Undo approval…'), icon: 'undo', fn: () => bw_unlock(m)} : null,
    can && !m.locked ? '-' : null,
    can && !m.locked ? {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: () => bw_delete(m)} : null]);
}
async function bw_delete(m, md) {
  if (!await askConfirm(tr('Delete the entertainment receipt “{0}”?', bw_title(m)), '', {ok: tr('Delete'), danger: true})) return;
  try {
    await api('DELETE', `${BW_U}/${m.id}`); md?.remove(); bw_reload();
    toast(tr('Deleted'), async () => { await api('POST', `${BW_U}/${m.id}/restore`); bw_reload(); });
  } catch (x) { toast(x.message || tr('unknown')); }
}
const BW_KEYS = ['date', 'place_name', 'place_address', 'occasion', 'host', 'guests', 'amounts', 'tip', 'note'];
const bw_body = m => Object.fromEntries(BW_KEYS.map(k => [k, m[k]]));
async function bw_dup(m) {  // a new draft with the same data (without the bill); opens it
  try {
    const j = await api('POST', BW_U, bw_body(m)); bw_reload();
    toast(tr('Copy created'), async () => { await api('DELETE', `${BW_U}/${j.id}`); bw_reload(); });
    bw_modal(j);
  } catch (x) { toast(x.message || tr('unknown')); }
}
async function bw_unlock(m, md) {
  const why = await askPrompt(tr('Undo the approval?'), '', {body: tr('The receipt becomes a draft again and can be changed. The log keeps who undid it, when and why.'), ok: tr('Undo approval'), input: {placeholder: tr('Reason (optional)'), max: 500}});
  if (why == null) return;
  try {
    const j = await api('POST', `${BW_U}/${m.id}/unlock`, {reason: why.trim()}); md?.remove(); bw_reload();
    toast(tr('Approval undone'), async () => { await api('POST', `${BW_U}/${m.id}/approve`); bw_reload(); });
    if (md) bw_modal(j);
  } catch (x) { toast(x.message || tr('unknown')); }
}
async function bw_approve(id) {
  const j = await api('POST', `${BW_U}/${id}/approve`); bw_reload();
  toast(tr('Approved and locked'), async () => { await api('POST', `${BW_U}/${id}/unlock`, {reason: tr('Undone right after approving')}); bw_reload(); });
  return j;
}

// ---- the mask
const bw_opt = (v, n, cur) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(n)}</option>`;
function bw_placeOpts(m) {
  const ch = BW.data?.choices?.places || [], cur = m?.place_name || '';
  const hit = ch.find(c => c.name.toLocaleLowerCase() === cur.toLocaleLowerCase() && (c.extra || '') === (m?.place_address || ''));
  const sel = hit ? `c${hit.id}` : cur ? 'cur' : '';
  return `<option value="" ${sel ? '' : 'selected'}>${esc(tr('Choose a place…'))}</option>${cur && !hit ? bw_opt('cur', cur, sel) : ''}${ch.map(c => bw_opt(`c${c.id}`, c.name, sel)).join('')}${bw_opt('__new', tr('New place…'), sel)}`;
}
function bw_hostOpts(m) {
  const me = BW.data?.me, h = m ? m.host : {id: me}, ppl = BW.data?.people || [], ch = BW.data?.choices?.persons || [];
  const hit = h?.id ? `u${h.id}` : h?.name ? (ch.find(c => c.name.toLocaleLowerCase() === h.name.toLocaleLowerCase()) ? `c${ch.find(c => c.name.toLocaleLowerCase() === h.name.toLocaleLowerCase()).id}` : 'cur') : '';
  return `<option value="" ${hit ? '' : 'selected'}>${esc(tr('Choose the host…'))}</option>${ppl.map(p => bw_opt(`u${p.id}`, p.name, hit)).join('')}${hit === 'cur' ? bw_opt('cur', bw_pn(h), hit) : ''}${ch.map(c => bw_opt(`c${c.id}`, bw_pn(c), hit)).join('')}${bw_opt('__new', tr('New person…'), hit)}`;
}
function bw_guestPool(m) {  // key -> {id} | {name, extra}: the people of the office, the choices, the meal's own guests
  const pool = new Map();
  for (const p of BW.data?.people || []) pool.set(rk_pkey(p), {id: p.id, name: p.name});
  for (const c of BW.data?.choices?.persons || []) if (!pool.has(rk_pkey(c))) pool.set(rk_pkey(c), {name: c.name, extra: c.extra || ''});
  for (const g of m?.guests || []) pool.set(rk_pkey(g), g);
  return pool;
}
const bw_guestHtml = (k, p, on) => `<label class="chkl bwg"><input type="checkbox" data-bwg="${esc(k)}" ${on ? 'checked' : ''}> <span>${esc(p.name)}${p.extra ? ` <small class="muted">${esc(p.extra)}</small>` : ''}</span></label>`;
const BW_KINDS = [['food', N_('Food')], ['drinks', N_('Drinks')]];
const bw_lineHtml = (l = {}) => `<li class="bwln"><select data-bwl="kind" aria-label="${esc(tr('Kind'))}">${BW_KINDS.map(([k, n]) => bw_opt(k, tr(n), l.kind || 'food')).join('')}</select>
  <select data-bwl="rate" aria-label="${esc(tr('VAT rate'))}">${[...new Set(['19', '7', '0', String(l.rate ?? '19')])].map(r => bw_opt(r, `${fmtNum(+r, +r % 1 ? 1 : 0)} %`, String(l.rate ?? '19'))).join('')}</select>
  <input data-bwl="gross" inputmode="decimal" class="numin" value="${l.gross != null ? esc(fmtNum(+l.gross, 2)) : ''}" placeholder="${esc(tr('Gross'))}" aria-label="${esc(tr('Gross amount'))}">
  <button type="button" class="iconbtn" data-bwm="rmline" aria-label="${esc(tr('Remove line'))}" title="${esc(tr('Remove line'))}">${ic('trash', 's')}</button></li>`;
function bw_fileHtml(m) {
  const fs = m?.files || [];
  const rows = fs.map(f => `<li class="bwf"><a href="${BW_U}/${m.id}/file/${f.id}${f.mime === 'application/pdf' ? '?inline=1' : ''}" target="_blank" rel="noopener"${f.mime === 'application/pdf' ? pv_attr({url: `${BW_U}/${m.id}/file/${f.id}?inline=1`, name: f.name, size: f.size, dlUrl: `${BW_U}/${m.id}/file/${f.id}`}) : ''}>${ic(f.mime === 'application/pdf' ? 'pdf' : 'picture', 's')}<span>${esc(f.name)}</span></a>
    ${m.locked ? '' : `<button type="button" class="iconbtn" data-bwm="rmfile" data-fid="${f.id}" aria-label="${esc(tr('Remove {0}', f.name))}" title="${esc(tr('Remove'))}">${ic('trash', 's')}</button>`}</li>`).join('');
  return (rows ? `<ul class="bwfiles" role="list">${rows}</ul>` : `<p class="muted bwnofile">${tr('No restaurant bill attached')}</p>`)
    + (m?.locked ? '' : `<button type="button" class="btn sm" data-bwm="file">${ic('upload', 's')}<span>${fs.length ? tr('Replace the bill') : tr('Attach the restaurant bill')}</span></button>`);
}
const bw_actLabel = e => e.action === 'approve' ? tr('Approved on {0} by {1}', bw_when(e.at), e.user || '–') : tr('Approval undone on {0} by {1}', bw_when(e.at), e.user || '–') + (e.reason ? ` – ${e.reason}` : '');
const bw_when = ts => { const d = new Date(ts); return isNaN(+d) ? ts : d.toLocaleString(LOCALE(), {dateStyle: 'medium', timeStyle: 'short'}); };
function bw_modal(m0) {
  let m = m0, pend = null;
  const ro = !!m?.locked;
  const pool = bw_guestPool(m), on = new Set((m?.guests || []).map(rk_pkey));
  const lines = m?.amounts?.length ? m.amounts : [{kind: 'food', rate: '19'}, {kind: 'drinks', rate: '19'}];
  const md = /** @type {any} */ (modal(`<h3>${m ? (ro ? tr('Entertainment receipt') : tr('Edit entertainment receipt')) : tr('New entertainment receipt')}</h3>
    ${ro ? `<p class="bwlocked">${ic('lock', 's')}<span>${esc(tr('Approved by {0} on {1}: locked.', m.approved_name || '–', bw_when(m.approved_at)))}</span></p>` : ''}
    <fieldset class="bwfs" ${ro ? 'disabled' : ''}>
    <div class="row"><label id="bw-dl">${tr('Date')}</label>${dateIn('bw-date', m?.date || new Date().toISOString().slice(0, 10), {label: tr('Date'), clear: false})}</div>
    ${ofcRowF('bw-place', tr('Place'), `<select id="bw-place">${bw_placeOpts(m)}</select>`)}
    <p class="muted ofchint bwpaddr"></p>
    <div class="bwpnew" hidden>${ofcRowF('bw-pname', tr('Name of the restaurant'), ofcIn('bw-pname', m?.place_name, {max: 120}))}
      <div class="row"><label for="bw-paddr">${tr('Address')}</label><textarea id="bw-paddr" rows="2" maxlength="400" placeholder="${esc(tr('Street, postcode and town'))}">${esc(m?.place_address || '')}</textarea></div></div>
    <div class="row"><label for="bw-occ">${tr('Occasion')}</label><textarea id="bw-occ" rows="2" maxlength="500" placeholder="${esc(tr('e.g. Negotiation of the follow-up order'))}">${esc(m?.occasion || '')}</textarea>
      <span class="muted ofchint">${tr('Be concrete: what was it about? “Business meal” alone is not enough.')}</span></div>
    ${ofcRowF('bw-host', tr('Host'), `<select id="bw-host">${bw_hostOpts(m)}</select>`)}
    <div class="bwhnew" hidden>${ofcRowF('bw-hname', tr('Name'), ofcIn('bw-hname', m?.host && !m.host.id ? m.host.name : '', {max: 120}))}${ofcRowF('bw-hextra', tr('Company or function'), ofcIn('bw-hextra', m?.host && !m.host.id ? m.host.extra : '', {max: 200}))}</div>
    <div class="row"><span class="rklab" id="bw-gl">${tr('Guests')}</span><div class="bwguests" role="group" aria-labelledby="bw-gl">${[...pool].map(([k, p]) => bw_guestHtml(k, p, on.has(k))).join('')}</div></div>
    ${ro ? '' : `<div class="bwgnew"><input id="bw-gname" maxlength="120" autocomplete="off" placeholder="${esc(tr('New person…'))}" aria-label="${esc(tr('Name of a new person'))}"><input id="bw-gextra" maxlength="200" autocomplete="off" placeholder="${esc(tr('Company or function'))}" aria-label="${esc(tr('Company or function'))}"><button type="button" class="btn sm" data-bwm="addguest">${ic('plus', 's')}<span>${tr('Add')}</span></button></div>`}
    <div class="row"><span class="rklab">${tr('Amounts (gross, as on the bill)')}</span><ul class="bwlines" role="list">${lines.map(bw_lineHtml).join('')}</ul>
      ${ro ? '' : `<button type="button" class="btn sm" data-bwm="addline">${ic('plus', 's')}<span>${tr('Add line')}</span></button>`}</div>
    ${ofcRowF('bw-tip', tr('Tip'), ofcIn('bw-tip', m && +m.tip ? fmtNum(+m.tip, 2) : '', {num: true, ph: tr('optional')}), tr('Not on the bill, no VAT; deductible like the bill.'))}
    <p class="bwsum" aria-live="polite"></p><p class="muted ofchint bw250" hidden>${tr('From 250 € gross the restaurant bill must be made out to the company.')}</p>
    <div class="row"><label for="bw-note">${tr('Note')}</label><textarea id="bw-note" rows="2" maxlength="2000">${esc(m?.note || '')}</textarea></div>
    </fieldset>
    <div class="row"><span class="rklab">${tr('Restaurant bill')}</span><div class="bwfilebox">${m ? bw_fileHtml(m) : `<button type="button" class="btn sm" data-bwm="file">${ic('upload', 's')}<span>${tr('Attach the restaurant bill')}</span></button><span class="muted bwpend"></span>`}</div></div>
    ${(m?.log || []).length ? `<div class="bwlogbox"><b>${tr('Approval log')}</b><ul class="bwlog" role="list">${m.log.map(e => `<li>${esc(bw_actLabel(e))}</li>`).join('')}</ul></div>` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot bwfoot">${ro ? `<button class="btn" data-bwm="unlock">${ic('undo', 's')}<span>${tr('Undo approval…')}</span></button>` : m ? `<button class="btn danger" data-bwm="del">${tr('Delete')}</button>` : ''}
      <span class="spacer"></span>${m ? `<button class="btn" data-bwm="pdf">${ic('pdf', 's')}<span>PDF</span></button>` : ''}
      <button class="btn" data-bwm="close">${ro ? tr('Close') : tr('Cancel')}</button>${ro ? '' : `<button class="btn" data-bwm="save">${tr('Save draft')}</button><button class="btn pri" data-bwm="approve">${ic('check', 's')}<span>${tr('Approve')}</span></button>`}</div>`));
  md.classList.add('ofcdlg', 'bwdlg');
  const close = ro ? () => md.remove() : fgModal(md);
  const err = msg => { const el = $('.aerr', md); if (el) el.textContent = msg || ''; };
  const val = id => /** @type {any} */ ($(id, md))?.value ?? '';
  const place = () => {  // a chosen place shows its address; "New place…" (or an old one not in the list) opens the fields
    const v = val('#bw-place'), c = (BW.data?.choices?.places || []).find(x => `c${x.id}` === v), box = $('.bwpnew', md);
    if (c) { /** @type {any} */ ($('#bw-pname', md)).value = c.name; /** @type {any} */ ($('#bw-paddr', md)).value = c.extra || ''; }
    else if (v === '__new' && !box.dataset.typed) { /** @type {any} */ ($('#bw-pname', md)).value = ''; /** @type {any} */ ($('#bw-paddr', md)).value = ''; }
    box.hidden = !(v === '__new' || v === 'cur');
    $('.bwpaddr', md).textContent = c ? (c.extra || tr('No address yet')).replace(/\n/g, ', ') : '';
  };
  const host = () => { $('.bwhnew', md).hidden = !['__new', 'cur'].includes(val('#bw-host')); };
  const lineVals = () => $$('.bwln', md).map(li => ({kind: /** @type {any} */ ($('[data-bwl="kind"]', li)).value, rate: /** @type {any} */ ($('[data-bwl="rate"]', li)).value, gross: ofcNum(/** @type {any} */ ($('[data-bwl="gross"]', li)).value)})).filter(l => l.gross);
  const sum = () => {
    const ls = lineVals(), bill = ls.reduce((s, l) => s + l.gross, 0), vat = ls.reduce((s, l) => s + (+l.rate ? l.gross * +l.rate / (100 + +l.rate) : 0), 0), tip = ofcNum(val('#bw-tip')) || 0;
    $('.bwsum', md).textContent = tr('Total {0} · of which VAT {1} · 70 % deductible {2}', bw_amt(bill + tip), bw_amt(vat), bw_amt((bill - vat + tip) * 0.7));
    $('.bw250', md).hidden = bill < 250;
  };
  const hostVal = () => {
    const v = val('#bw-host');
    if (v.startsWith('u')) return {id: +v.slice(1)};
    const c = (BW.data?.choices?.persons || []).find(x => `c${x.id}` === v);
    if (c) return {name: c.name, extra: c.extra || ''};
    return v ? {name: val('#bw-hname').trim(), extra: val('#bw-hextra').trim()} : null;
  };
  const collect = () => ({date: val('#bw-date'), place_name: val('#bw-pname').trim(), place_address: val('#bw-paddr').trim(), occasion: val('#bw-occ').trim(), host: hostVal(),
    guests: $$('[data-bwg]', md).filter(x => /** @type {any} */ (x).checked).map(x => pool.get(x.dataset.bwg)).filter(Boolean).map(p => p.id ? {id: p.id} : {name: p.name, extra: p.extra || ''}),
    amounts: lineVals(), tip: ofcNum(val('#bw-tip')), note: val('#bw-note')});
  const save = async () => {  // POST / PATCH; one undo step; -> the stored meal
    const b = collect();
    if (m) {
      const old = bw_body(m);
      m = await api('PATCH', `${BW_U}/${m.id}`, b);
      const id = m.id; toast(tr('Saved'), async () => { await api('PATCH', `${BW_U}/${id}`, old); bw_reload(); });
    } else {
      m = await api('POST', BW_U, b);
      if (pend) { try { m = await api('POST', `${BW_U}/${m.id}/file`, bw_fd(pend)); } catch (x) { toast(x.message || ''); } }
      const id = m.id; toast(tr('Added'), async () => { await api('DELETE', `${BW_U}/${id}`); bw_reload(); });
    }
    return m;
  };
  md.addEventListener('change', e => {
    const t = /** @type {any} */ (e.target);
    if (t.id === 'bw-place') place();
    else if (t.id === 'bw-host') host();
    sum();
  });
  md.addEventListener('input', e => { if (/** @type {any} */ (e.target).id === 'bw-pname') $('.bwpnew', md).dataset.typed = '1'; sum(); });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && /** @type {any} */ (e.target).closest?.('.bwgnew')) { e.preventDefault(); /** @type {any} */ ($('[data-bwm="addguest"]', md))?.click(); } });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-bwm]'); if (!b) return;
    const a = b.dataset.bwm;
    if (a === 'close') { close(); return; }
    if (a === 'addline') { $('.bwlines', md).insertAdjacentHTML('beforeend', bw_lineHtml({kind: 'food', rate: '19'})); /** @type {any} */ ($('.bwln:last-child [data-bwl="gross"]', md))?.focus(); return; }
    if (a === 'rmline') { b.closest('.bwln')?.remove(); sum(); return; }
    if (a === 'addguest') {
      const name = val('#bw-gname').trim(), extra = val('#bw-gextra').trim(); if (!name) { /** @type {any} */ ($('#bw-gname', md)).focus(); return; }
      const p = {name, extra}, k = rk_pkey(p); pool.set(k, p);
      const ex = $(`[data-bwg="${CSS.escape(k)}"]`, md);
      if (ex) { /** @type {any} */ (ex).checked = true; ex.closest('label').outerHTML = bw_guestHtml(k, p, true); } else $('.bwguests', md).insertAdjacentHTML('beforeend', bw_guestHtml(k, p, true));
      /** @type {any} */ ($('#bw-gname', md)).value = ''; /** @type {any} */ ($('#bw-gextra', md)).value = ''; /** @type {any} */ ($('#bw-gname', md)).focus();
      return;
    }
    err('');
    try {
      if (a === 'pdf') { bw_openPdf(m); return; }
      if (a === 'unlock') { await bw_unlock(m, md); return; }
      if (a === 'del') { await bw_delete(m, md); return; }
      if (a === 'file') { bw_pick(async f => {
        if (!m) { pend = f; $('.bwpend', md).textContent = tr('{0} is attached when you save', f.name); return; }
        try {
          const j = await api('POST', `${BW_U}/${m.id}/file`, bw_fd(f)), id = m.id; m = j; $('.bwfilebox', md).innerHTML = bw_fileHtml(m); bw_reload();
          toast(tr('Attached'), async () => { await api('DELETE', `${BW_U}/${id}/file/${j.file_id}`); for (const o of j.replaced || []) await api('POST', `${BW_U}/${id}/file/${o}/restore`); bw_reload(); });
        } catch (x) { err(x.message); }
      }); return; }
      if (a === 'rmfile') {
        const fid = +b.dataset.fid, id = m.id; m = await api('DELETE', `${BW_U}/${id}/file/${fid}`); $('.bwfilebox', md).innerHTML = bw_fileHtml(m); bw_reload();
        toast(tr('Removed'), async () => { await api('POST', `${BW_U}/${id}/file/${fid}/restore`); bw_reload(); });
        return;
      }
      if (a === 'save') { await save(); md.remove(); bw_reload(); return; }
      if (a === 'approve') {
        await save(); bw_reload();
        try { await bw_approve(m.id); md.remove(); }
        catch (x) { md.remove(); bw_modal(m).querySelector('.aerr').textContent = tr('Saved as a draft.') + ' ' + (x.message || ''); }
      }
    } catch (x) { err(x.message); }
  });
  place(); host(); sum();
  return md;
}
function bw_fd(f) { const fd = new FormData(); fd.append('file', f, f.name || 'bill.pdf'); return fd; }
function bw_pick(done) {
  const i = document.createElement('input'); i.type = 'file'; i.accept = 'application/pdf,.pdf,image/jpeg,image/png';
  i.onchange = () => { if (i.files[0]) done(i.files[0]); }; i.click();
}

// ---- the evaluation (approved receipts only), CSV / PDF with the same filters
async function bw_loadReport() {
  const q = bw_q();
  try { BW.rep = Object.assign(await api('GET', `${BW_U}/report?${q}`), {q}); } catch (x) { BW.rep = {error: x.message || tr('unknown'), q}; }
  ofcDraw();
}
function bw_reportHtml() {
  const q = bw_q();
  if (!BW.rep || BW.rep.q !== q) { setTimeout(bw_loadReport, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const r = BW.rep; if (r.error) return `<div class="empty">${esc(r.error)}</div>`;
  const t = r.total, dl = ext => `<a class="btn sm" href="${BW_U}/report?${esc(q)}&format=${ext}" download>${ic('download', 's')}<span>${ext.toUpperCase()}</span></a>`;
  const card = (lab, v, cls = '') => `<div class="bwcard ${cls}"><small class="muted">${esc(lab)}</small><b>${bw_amt(v)}</b></div>`;
  const drafts = r.drafts ? `<p class="muted ofchint">${esc(trn('{0} draft is not in the sums.', '{0} drafts are not in the sums.', r.drafts))}</p>` : '';
  if (!r.count) return `<div class="ofcbar"><b>${tr('Evaluation')}</b><span class="spacer"></span>${dl('csv')}${dl('pdf')}</div><div class="empty nempty">${tr('No approved entertainment receipts in this period.')}</div>${drafts}`;
  const kind = k => tr(BW_KINDS.find(x => x[0] === k)?.[1] || k);
  return `<div class="ofcbar"><b>${esc(trn('{0} approved receipt', '{0} approved receipts', r.count))}</b><span class="spacer"></span>${dl('csv')}${dl('pdf')}</div>
    <div class="bwcards">${card(tr('Gross'), t.gross)}${card(tr('Input VAT (100 %)'), t.vat)}${card(tr('Deductible 70 %'), t.deductible, 'bwmain')}${card(tr('Not deductible 30 %'), t.not_deductible)}</div>
    <table class="rktab bwtab"><tbody><tr><td>${tr('Food')}</td><td class="num">${bw_amt(t.food)}</td></tr><tr><td>${tr('Drinks')}</td><td class="num">${bw_amt(t.drinks)}</td></tr>
      <tr><td>${tr('Tip (no VAT)')}</td><td class="num">${bw_amt(t.tip)}</td></tr><tr><td>${tr('Net incl. tip')}</td><td class="num">${bw_amt(t.net)}</td></tr></tbody></table>
    <table class="rktab bwtab"><thead><tr><th>${tr('Input VAT by rate')}</th><th class="num">${tr('Gross')}</th><th class="num">${tr('VAT')}</th></tr></thead><tbody>${r.rates.map(g => `<tr><td>${esc(kind(g.kind))} ${fmtNum(+g.rate, +g.rate % 1 ? 1 : 0)} %</td><td class="num">${bw_amt(g.gross)}</td><td class="num">${bw_amt(g.vat)}</td></tr>`).join('')}</tbody></table>
    <table class="rktab bwtab"><thead><tr><th>${tr('Month')}</th><th class="num">${tr('Receipts')}</th><th class="num">${tr('Gross')}</th><th class="num">${tr('Deductible 70 %')}</th></tr></thead><tbody>${r.months.map(g => `<tr><td>${esc(rk_month(g.key))}</td><td class="num muted">${g.count}</td><td class="num">${bw_amt(g.gross)}</td><td class="num">${bw_amt(g.deductible)}</td></tr>`).join('')}</tbody></table>
    ${drafts}<p class="muted ofchint">${tr('70 % of the net amount (incl. tip) is deductible as a business expense, the input VAT in full. Kalmido does not replace tax advice.')}</p>`;
}

// ---- events
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-bw]'); if (!b || b.tagName === 'INPUT') return;
  const a = b.dataset.bw;
  if (a === 'new') bw_modal(null);
  else if (a === 'open') { const m = bw_meal(+b.dataset.id); if (m) bw_modal(m); }
  else if (a === 'rowmore') bw_rowMenu(b.dataset.id, b);
  else if (a === 'view') { BW.view = b.dataset.v; ofcDraw(); }
  else return;
  e.preventDefault();
});
document.addEventListener('contextmenu', e => {  // right click on a row: the same menu
  const r = /** @type {any} */ (e.target).closest?.('.bwlist .ofcrow[data-bw="open"]'); if (!r) return;
  e.preventDefault(); bw_rowMenu(r.dataset.id, r);
});
let bw_occT = 0;
document.addEventListener('input', e => {  // the occasion filter: the list at once, the evaluation after a pause
  const x = /** @type {any} */ (e.target); if (x.id !== 'bw-occf') return;
  clearTimeout(bw_occT);
  bw_occT = setTimeout(() => { BW.occ = x.value; ofcDraw(); const f = /** @type {any} */ ($('#bw-occf')); if (f) { f.focus(); f.setSelectionRange?.(f.value.length, f.value.length); } }, 250);
});
document.addEventListener('change', e => {
  const x = /** @type {any} */ (e.target);
  if (x.id === 'bw-year') { BW.year = x.value; bw_reload(); }
  else if (x.id === 'bw-person') { BW.person = x.value; BW.personName = x.selectedOptions[0]?.textContent || ''; BW.rep = null; ofcDraw(); /** @type {any} */ ($('#bw-person'))?.focus(); }
});

// ---- the section "Entertainment receipts" in the office settings (admins): places and people of the choice lists, rename in
// place (saved on leaving the field), remove with undo, add; no save button (like the purposes of the travel expenses)
const BWC = {data: null, oid: undefined};
async function bw_choicesLoad() {
  BWC.oid = OFC.info?.org_id;
  try { BWC.data = await api('GET', `${BW_U}/choices`); } catch (x) { BWC.data = {places: [], persons: []}; toast(x.message || tr('unknown')); }
  const sec = $('.bwcset'); if (sec) sec.outerHTML = bw_settingsHtml();  // only this section: the settings form keeps what is typed there
}
function bw_settingsHtml() {
  if (!ofcAdmin()) return '';
  if (BWC.oid !== OFC.info?.org_id) { BWC.oid = OFC.info?.org_id; BWC.data = null; setTimeout(bw_choicesLoad, 0); }
  const d = BWC.data;
  const list = (kind, items, ph) => `<ul class="rkplist bwclist" role="list">${items.map(c => `<li><input value="${esc(c.name)}" maxlength="120" data-bwc="name" data-id="${c.id}" aria-label="${esc(tr('Name'))}"><input value="${esc(c.extra || '')}" maxlength="200" data-bwc="extra" data-id="${c.id}" placeholder="${esc(ph)}" aria-label="${esc(ph)}"><button type="button" class="iconbtn" data-bwc="del" data-id="${c.id}" aria-label="${esc(tr('Remove {0}', c.name))}" title="${esc(tr('Remove'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>
    <div class="lacts bwcadd"><input data-bwc-new="name" data-kind="${kind}" maxlength="120" autocomplete="off" placeholder="${esc(kind === 'place' ? tr('New place…') : tr('New person…'))}" aria-label="${esc(tr('Name'))}"><input data-bwc-new="extra" maxlength="200" autocomplete="off" placeholder="${esc(ph)}" aria-label="${esc(ph)}"><button type="button" class="btn sm" data-bwc="add" data-kind="${kind}">${ic('plus', 's')}<span>${tr('Add')}</span></button></div>`;
  return `<section class="rkpset bwcset" data-fg-skip aria-labelledby="bwc-h"><h3 id="bwc-h">${tr('Entertainment receipts')}</h3>
    <p class="muted ofchint">${tr('The choices for places and people. New ones are added when a receipt is approved; receipts keep what they have when you rename or remove one.')}</p>
    ${!d ? `<p class="muted">${tr('Loading…')}</p>` : `<h4>${tr('Places')}</h4>${list('place', d.places, tr('Address'))}<h4>${tr('People')}</h4>${list('person', d.persons, tr('Company or function'))}`}</section>`;
}
async function bw_choiceAct(a, el) {
  const all = [...(BWC.data?.places || []), ...(BWC.data?.persons || [])];
  try {
    if (a === 'add') {
      const row = el.closest('.bwcadd'), n = /** @type {any} */ ($('[data-bwc-new="name"]', row)), x = /** @type {any} */ ($('[data-bwc-new="extra"]', row)), name = n.value.trim();
      if (!name) { n.focus(); return; }
      const j = await api('POST', `${BW_U}/choices`, {kind: el.dataset.kind, name, extra: x.value.trim()}); BW.data = null; await bw_choicesLoad();
      toast(tr('Added'), async () => { await api('DELETE', `${BW_U}/choices/${j.id}`); BW.data = null; bw_choicesLoad(); });
    } else if (a === 'del') {
      const j = await api('DELETE', `${BW_U}/choices/${el.dataset.id}`); BW.data = null; await bw_choicesLoad();
      toast(tr('Removed'), async () => { await api('POST', `${BW_U}/choices`, j.choice); BW.data = null; bw_choicesLoad(); });
    } else {
      const old = all.find(c => c.id === +el.dataset.id), v = el.value.trim(); if (!old || v === (old[a] || '')) return;
      if (a === 'name' && !v) { el.value = old.name; return; }
      const was = old[a] || '';
      await api('PATCH', `${BW_U}/choices/${old.id}`, {[a]: v}); BW.data = null; old[a] = v;
      toast(tr('Saved'), async () => { await api('PATCH', `${BW_U}/choices/${old.id}`, {[a]: was}); BW.data = null; bw_choicesLoad(); });
    }
  } catch (x) { if (a === 'name' || a === 'extra') { const o = all.find(c => c.id === +el.dataset.id); if (o) el.value = o[a] || ''; } toast(x.message || tr('unknown')); }
}
document.addEventListener('click', e => { const b = /** @type {any} */ (e.target).closest?.('button[data-bwc]'); if (!b) return; e.preventDefault(); bw_choiceAct(b.dataset.bwc, b); });
document.addEventListener('change', e => { const x = /** @type {any} */ (e.target); if (['name', 'extra'].includes(x.dataset?.bwc)) bw_choiceAct(x.dataset.bwc, x); });
document.addEventListener('keydown', e => {
  const x = /** @type {any} */ (e.target); if (e.key !== 'Enter' || e.isComposing || !x.closest?.('.bwcset') || x.tagName !== 'INPUT') return;
  e.preventDefault(); e.stopPropagation();  // never the settings form's submit
  if (x.dataset.bwcNew) /** @type {any} */ ($('button[data-bwc="add"]', x.closest('.bwcadd')))?.click(); else x.blur();
}, true);
