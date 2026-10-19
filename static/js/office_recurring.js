// 2.91.0 A (#1923): invoice series in the office (admins of the office area): an invoice repeated every month / quarter / year
// from a template invoice. The editor of an invoice offers "Repeat as series" (a sheet: interval, first period, end, send
// automatically, the placeholders), the invoice list a section "Invoice series" (next date, amount, on / paused, make now,
// edit, delete with undo, the bin), an invoice made by a series a hint with its period. Every action is one undo step.
// Server: kalmido/office/recurring.py.
const RIN = {items: null, docs: {}, loading: false, err: null, oid: null, listRef: undefined, bin: null, showBin: false, open: false};
const RIN_EVERY = [['monthly', N_('monthly')], ['quarterly', N_('quarterly')], ['yearly', N_('yearly')]];
const RIN_PH = [['{period}', N_('the period of service, e.g. 01.10.2026 - 31.10.2026')], ['{month}', N_('the month, e.g. October 2026')],
  ['{quarter}', N_('the quarter, e.g. Q4 2026')], ['{year}', N_('the year, e.g. 2026')]];
if (typeof OFD_ACTIONS === 'object') Object.assign(OFD_ACTIONS, {series: N_('created by an invoice series'), series_create: N_('invoice series created'),
  series_update: N_('invoice series changed'), series_delete: N_('invoice series deleted'), series_restore: N_('invoice series restored')});

const rinEvery = v => tr(RIN_EVERY.find(x => x[0] === v)?.[1] || v);
const rinOn = () => typeof ofcAdmin === 'function' && ofcAdmin();
function rinFresh() {
  if (RIN.oid !== OFC.info?.org_id) Object.assign(RIN, {oid: OFC.info?.org_id, items: null, docs: {}, bin: null, err: null});
  if (rinOn() && !RIN.items && !RIN.loading && !RIN.err) setTimeout(rinLoad, 0);
}
async function rinLoad() {
  RIN.loading = true;
  try { const j = await api('GET', '/api/office/series'); RIN.items = j.items || []; RIN.docs = j.docs || {}; RIN.err = null; }
  catch (x) { RIN.items = RIN.items || []; RIN.err = x.message || tr('unknown'); }
  RIN.loading = false;
  if (RIN.showBin) { try { RIN.bin = (await api('GET', '/api/office/series?bin=1')).items || []; } catch { RIN.bin = []; } }
  if (typeof ofdDraw === 'function') ofdDraw();
}
const rinReload = () => { RIN.items = null; RIN.err = null; rinLoad(); };
const rinById = id => (RIN.items || []).find(s => s.id === +id) || (RIN.bin || []).find(s => s.id === +id);
const rinWhen = s => !s.active ? (s.until && s.next_date > s.until ? tr('ended') : tr('paused')) : s.next_date ? tr('next on {0}', fmtDateLoc(s.next_date)) : '';
const rinPeriodTxt = (p, s) => { const n = rinNext(p, s); return `${fmtDateLoc(p)} – ${fmtDateLoc(rinDay(n, -1))}`; };
function rinDay(iso, add) { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + add); return d.toISOString().slice(0, 10); }
function rinNext(p, s) {  // the next period start after p (the day of the series' start kept, the 31st = the month's last day)
  if (!s) return rinDay(p, 31);
  const st = s.start || p, step = {monthly: 1, quarterly: 3, yearly: 12}[s.every] || 1;
  const [y, m, d] = st.split('-').map(Number);
  for (let i = 0; i < 1200; i++) {
    const mm = m - 1 + i * step, yy = y + Math.floor(mm / 12), mo = mm % 12;
    const last = new Date(yy, mo + 1, 0).getDate(), iso = `${yy}-${String(mo + 1).padStart(2, '0')}-${String(Math.min(d, last)).padStart(2, '0')}`;
    if (iso > p) return iso;
  }
  return p;
}

// ---- the invoice list: the section of the series (above the invoices) and the hint on an invoice of a series
function rinListHtml() {
  if (!rinOn()) return '';
  if (RIN.listRef !== OFD.list && OFD.list) { RIN.listRef = OFD.list; if (RIN.items && !RIN.loading) setTimeout(rinReload, 0); }
  rinFresh();
  const items = RIN.items || [];
  if (!items.length && !RIN.showBin) return '';
  const row = s => `<li class="rin-it${s.active ? '' : ' rin-off'}" data-sid="${s.id}"><span class="ofcn"><b>${esc(s.title || tr('Invoice series'))}${s.template?.client ? ` · ${esc(s.template.client)}` : ''}</b>
    <small class="muted">${esc([rinEvery(s.every), rinWhen(s), s.auto_send ? tr('sent automatically') : tr('as a draft')].filter(Boolean).join(' · '))}</small></span>
    <b class="rin-sum">${esc(s.template?.gross_text || '')}</b>
    <span class="rin-acts"><label class="chkl swl" title="${esc(s.active ? tr('Active') : tr('Paused'))}"><span class="swc"><input type="checkbox" role="switch" data-rin="active" data-sid="${s.id}" ${s.active ? 'checked' : ''} aria-label="${esc(tr('Active'))}"><span class="swt" aria-hidden="true"></span></span></label>
    <button type="button" class="btn sm" data-rin="run" data-sid="${s.id}" ${s.active || !(s.until && s.next_date > s.until) ? '' : 'disabled'}>${ic('plus', 's')}<span>${tr('Make now')}</span></button>
    <button type="button" class="ib" data-rin="edit" data-sid="${s.id}" aria-label="${esc(tr('Edit'))}">${ic('edit', 's')}</button>
    <button type="button" class="ib" data-rin="del" data-sid="${s.id}" aria-label="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span></li>`;
  const bin = RIN.showBin ? `<h4 class="ofcgrp">${tr('Deleted series')}</h4>${(RIN.bin || []).length ? `<ul class="ofclist rin-list" role="list">${RIN.bin.map(s => `<li class="rin-it rin-off"><span class="ofcn"><b>${esc(s.title || tr('Invoice series'))}</b><small class="muted">${esc(rinEvery(s.every))}</small></span><button type="button" class="btn sm" data-rin="restore" data-sid="${s.id}">${tr('Restore')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('Nothing deleted.')}</p>`}` : '';
  return `<details class="ofdsec rin-sec" ${RIN.open ? 'open' : ''} data-rin-sec><summary><h3>${tr('Invoice series')}</h3><span class="c muted">${items.length}</span></summary><div class="ofdsecb">
    ${items.length ? `<ul class="ofclist rin-list" role="list">${items.map(row).join('')}</ul>` : ''}${bin}
    <div class="lacts"><button type="button" class="linkbtn" data-rin="bin">${RIN.showBin ? tr('Hide deleted series') : tr('Deleted series')}</button></div>
    <p class="muted ofchint">${tr('A new series starts in the editor of an invoice: "Repeat as series".')}</p></div></details>`;
}
function rinRowTag(r) {
  const x = RIN.docs?.[r.id]; if (!x) return '';
  const s = rinById(x[0]);
  return `<small class="rin-tag">${ic('repeat', 's')}${esc(tr('Series {0}', s?.title || ''))}</small>`;
}

// ---- the editor of an invoice: the hint "from series" / "template of", the button
function rinBox(d) {
  if (!d || d.kind !== 'invoice' || !rinOn()) return '';
  rinFresh();
  const out = [];
  if (d.series_id) {
    const s = rinById(d.series_id);
    out.push(`<p class="muted ofchint rin-from">${ic('repeat', 's')}<span>${esc(tr('From series {0}, period {1}', s?.title || '#' + d.series_id, d.series_period ? rinPeriodTxt(d.series_period, s) : ''))}</span>${s && !s.deleted ? ` <button type="button" class="linkbtn" data-rin="edit" data-sid="${s.id}">${tr('Edit series')}</button>` : ''}</p>`);
  }
  const tpl = (RIN.items || []).filter(s => s.template_id === d.id);
  for (const s of tpl) out.push(`<p class="muted ofchint rin-from">${ic('repeat', 's')}<span>${esc(tr('Template of series {0} ({1}, {2})', s.title || '', rinEvery(s.every), rinWhen(s)))}</span> <button type="button" class="linkbtn" data-rin="edit" data-sid="${s.id}">${tr('Edit series')}</button></p>`);
  const btn = d.status !== 'cancelled' ? `<button type="button" class="btn sm" data-rin="new" data-did="${d.id}">${ic('repeat', 's')}<span>${tr('Repeat as series')}</span></button>` : '';
  return `<div class="rin-box">${out.join('')}${btn ? `<div class="lacts">${btn}</div>` : ''}</div>`;
}

// ---- the sheet: a new series from invoice d, or series s changed
function rinFirstStart(d) {
  const t = new Date(), nextFirst = new Date(t.getFullYear(), t.getMonth() + 1, 1);
  const iso = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  if (!d.service_from) return iso(nextFirst);
  return d.locked || d.status !== 'draft' ? rinNext(d.service_from, {start: d.service_from, every: 'monthly'}) : d.service_from;
}
function rinSheet(d, s) {
  const v = s || {every: 'monthly', start: rinFirstStart(d), until: '', auto_send: 0, title: d.project_title || d.recipient?.name || ''};
  const ph = `<details class="rin-ph"><summary>${tr('Placeholders in the texts')}</summary><ul role="list">${RIN_PH.map(([k, n]) => `<li><code>${k}</code> ${esc(tr(n))}</li>`).join('')}</ul>
    <p class="muted">${tr('They work in the project title, the introduction, the closing and the positions of the template; the template keeps them.')}</p></details>`;
  const body = ofdF('rin-title', tr('Name'), `<input id="ofd-rin-title" value="${esc(v.title || '')}" maxlength="200">`)
    + ofdF('rin-every', tr('Interval'), `<div class="seg rin-every" role="radiogroup" aria-label="${esc(tr('Interval'))}">${RIN_EVERY.map(([k, n]) => `<button type="button" role="radio" data-rin-every="${k}" aria-checked="${v.every === k}" class="${v.every === k ? 'on' : ''}">${esc(tr(n))}</button>`).join('')}</div>`)
    + ofdF('rin-start', tr('First period of service from'), dateIn('ofd-rin-start', v.start, {label: tr('First period of service from'), clear: false}))
    + ofdF('rin-until', tr('Last period from (optional)'), dateIn('ofd-rin-until', v.until || '', {label: tr('Last period from (optional)'), after: 'ofd-rin-start'}))
    + `<div class="row"><label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="ofd-rin-auto" ${v.auto_send ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('Send automatically')}</span></label>
      <span class="muted ofchint">${tr('Finalised and mailed to the client on the day of the period. Otherwise a draft is made that you check and send.')}</span></div>` + ph;
  const md = ofdDlg(s ? tr('Edit invoice series') : tr('Repeat as series'), body, s ? tr('Save') : tr('Create'), async m => {
    const b = {title: $('#ofd-rin-title', m).value.trim(), every: $('[data-rin-every].on', m)?.dataset.rinEvery || 'monthly', start: $('#ofd-rin-start', m).value,
      until: $('#ofd-rin-until', m).value || '', auto_send: $('#ofd-rin-auto', m).checked ? 1 : 0};
    if (s) {
      const old = {title: s.title, every: s.every, start: s.start, until: s.until, auto_send: s.auto_send, next_date: s.next_date};
      await rawFetch('PATCH', `/api/office/series/${s.id}`, b);
      offerUndo(tr('Saved'), histAdd({label: tr('Invoice series changed'), undo: () => rinPatch(s.id, old), redo: () => rinPatch(s.id, b)}));
    } else {
      const j = await rawFetch('POST', '/api/office/series', {...b, template_id: d.id});
      RIN.open = true;
      offerUndo(tr('Invoice series created'), histAdd({label: tr('Invoice series created'), undo: () => rinDo('DELETE', `/api/office/series/${j.id}`), redo: () => rinDo('POST', `/api/office/series/${j.id}/restore`)}));
    }
    rinReload();
  });
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-rin-every]'); if (!b) return;
    md.querySelectorAll('[data-rin-every]').forEach(x => { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-checked', on); });
  });
}
async function rinDo(method, url, body) { try { await rawFetch(method, url, body); } catch (x) { toast(x.message || tr('unknown')); } rinReload(); }
const rinPatch = (id, b) => rinDo('PATCH', `/api/office/series/${id}`, b);

// ---- clicks (the list section, the editor box, the cash flow's jump)
async function rinClick(e) {
  const go = e.target.closest('[data-rin-go]');
  if (go) { if (typeof OFD === 'object') { OFD.kind = 'invoice'; OFD.list = null; } RIN.open = true; return; }
  const b = e.target.closest('[data-rin]'); if (!b || !b.closest('.office')) return;
  const a = b.dataset.rin, s = rinById(b.dataset.sid);
  if (a === 'active') return;  // the change event below
  e.preventDefault();
  if (a === 'new') { if (OFD.doc && OFD.doc.id === +b.dataset.did) rinSheet(OFD.doc); return; }
  if (a === 'bin') { RIN.showBin = !RIN.showBin; RIN.open = true; rinReload(); return; }
  if (a === 'edit' && s) { rinSheet(OFD.doc && OFD.doc.id === s.template_id ? OFD.doc : {}, s); return; }
  if (a === 'restore' && s) { await rinDo('POST', `/api/office/series/${s.id}/restore`); offerUndo(tr('Restored'), histAdd({label: tr('Invoice series restored'), undo: () => rinDo('DELETE', `/api/office/series/${s.id}`), redo: () => rinDo('POST', `/api/office/series/${s.id}/restore`)})); return; }
  if (a === 'del' && s) {
    try { await rawFetch('DELETE', `/api/office/series/${s.id}`); } catch (x) { toast(x.message || tr('unknown')); return; }
    rinReload();
    offerUndo(tr('Invoice series deleted'), histAdd({label: tr('Invoice series deleted'), undo: () => rinDo('POST', `/api/office/series/${s.id}/restore`), redo: () => rinDo('DELETE', `/api/office/series/${s.id}`)}));
    return;
  }
  if (a === 'run' && s) {
    if (s.auto_send && !await askConfirm(tr('Make and send the invoice now?'), tr('The invoice of the next period is finalised and mailed to the client at once.'), {ok: tr('Send|mail')})) return;
    b.disabled = true;
    let j;
    try { j = await rawFetch('POST', `/api/office/series/${s.id}/run`); } catch (x) { b.disabled = false; toast(x.message || tr('unknown')); rinReload(); return; }
    OFD.list = null;
    rinReload();
    if (j.error) toast(j.error);
    if (j.sent) { toast(tr('Invoice sent')); return; }  // a mail cannot be taken back: no undo step
    const prev = j.prev_next_date;
    offerUndo(tr('Invoice draft created'), histAdd({label: tr('Invoice draft created'),
      undo: async () => { try { await rawFetch('DELETE', `/api/office/docs/${j.doc_id}`); } catch (x) { toast(x.message || tr('unknown')); } OFD.list = null; await rinPatch(s.id, {next_date: prev}); },
      redo: async () => { try { const k = await rawFetch('POST', `/api/office/series/${s.id}/run`); j.doc_id = k.doc_id; } catch (x) { toast(x.message || tr('unknown')); } OFD.list = null; rinReload(); }}));
  }
}
async function rinChange(e) {
  const b = e.target.closest('[data-rin="active"]'); if (!b) return;
  const id = +b.dataset.sid, on = b.checked ? 1 : 0;
  try { await rawFetch('PATCH', `/api/office/series/${id}`, {active: on}); } catch (x) { b.checked = !on; toast(x.message || tr('unknown')); return; }
  rinReload();
  offerUndo(on ? tr('Invoice series active') : tr('Invoice series paused'), histAdd({label: on ? tr('Invoice series active') : tr('Invoice series paused'), undo: () => rinPatch(id, {active: on ? 0 : 1}), redo: () => rinPatch(id, {active: on})}));
}
function rinToggle(e) { const d = e.target.closest?.('[data-rin-sec]'); if (d) RIN.open = d.open; }
if (!window._rinBound) {
  window._rinBound = true;
  document.addEventListener('click', rinClick);
  document.addEventListener('change', rinChange);
  document.addEventListener('toggle', rinToggle, true);
}
