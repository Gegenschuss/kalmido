// 2.92.0 A (#1925): business contracts and insurances in the office (tab "Contracts & insurance", admins of the office area
// only): grouped by kind, per row the contribution per month (and as entered), the next last day to cancel (red from the
// lead time on) and the contract document. The editor holds every field, the document of the office's documents space
// (choose or upload), "Deadline as a task" (one task in a list the admin picks, the agent "contracts in view" reminds of it)
// and "In the cash flow" (the contribution is an outflow like a fixed cost). Every action is one undo step; deleting is
// soft (the undo restores). Server: kalmido/office/agreements.py.
const AGR = {data: null, err: null, oid: null, arch: false, seq: 0, opened: null};
const AGR_KINDS = [['insurance', N_('Insurances')], ['rent', N_('Rent|office')], ['leasing', N_('Leasing')], ['service', N_('Service providers')], ['other', N_('Other')]];
const AGR_KIND1 = {insurance: N_('Insurance'), rent: N_('Rent|office'), leasing: N_('Leasing'), service: N_('Service provider'), other: N_('Other')};
const AGR_PERS = [['month', N_('per month')], ['quarter', N_('per quarter')], ['year', N_('per year')]];
const AGR_UNITS = [['d', N_('days')], ['w', N_('weeks')], ['m', N_('months')]];
const AGR_RENEW = [0, 1, 3, 6, 12, 24, 36, 60];
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['agreements', 'shield', N_('Contracts & insurance'), 1, () => agrHtml(), 'admin']);  // admins only; 2.92.1 (#1917): in the menu group Administration

async function agrLoad() {
  const seq = ++AGR.seq;
  try { const j = await api('GET', '/api/office/agreements' + (AGR.arch ? '?archived=1' : '')); if (seq === AGR.seq) { AGR.data = j; AGR.err = null; } }
  catch (x) { if (seq === AGR.seq) AGR.err = x.message || tr('unknown'); }
  ofcDraw();
}
const agrReload = () => { AGR.data = null; if (typeof RKF === 'object') RKF.data = null; if (S.route.mod === 'office' && ofcTab() === 'agreements') agrLoad(); };
const agrPer = p => tr(AGR_PERS.find(x => x[0] === p)?.[1] || p);
const agrUnit = u => tr(AGR_UNITS.find(x => x[0] === u)?.[1] || u);

function agrDeadline(a) {
  const d = a.deadline; if (!d) return a.ends ? '' : tr('No end of term');
  const when = tr('Cancel by {0}', fmtDateLoc(d.cancel_by));
  if (d.over) return `<span class="agr-late">${esc(when)} · ${esc(tr('passed'))}</span>`;
  const left = d.days === 0 ? tr('today') : trn('{0} day left', '{0} days left', d.days);
  return `<span class="${d.warn ? 'agr-late' : ''}">${esc(when)} · ${esc(left)}</span>`;
}
function agrRow(a) {
  const sub = [a.provider, a.number, a.archived ? tr('Archived') : ''].filter(Boolean).map(esc).join(' · ');
  const sum = a.monthly != null ? `<span class="rksum agr-sum"><span>${ofcMoney(a.monthly)} <small class="muted">${tr('per month')}</small></span>${a.per !== 'month' ? `<small class="muted">${ofcMoney(a.cost)} ${esc(agrPer(a.per))}</small>` : ''}</span>` : '';
  const doc = a.doc ? `<a class="iconbtn agr-doc" href="#docs/${a.doc.id}" aria-label="${esc(tr('Open document {0}', a.doc.name))}" title="${esc(a.doc.name)}">${ic('file', 's')}</a>` : '';
  const fold = !a.archived && typeof fsr_fileMenu === 'function' ? `<button type="button" class="iconbtn agr-fold" data-agrfold="${a.id}" aria-haspopup="menu" title="${esc(tr('Move to folder…'))}" aria-label="${esc(tr('Move to folder…'))}: ${esc(a.name)}">${ic('folder', 's')}</button>` : '';  // 2.351.0 B (#2749)
  return `<li class="agr-li${a.archived ? ' agr-arch' : ''}"><button type="button" class="ofcrow" data-agr="open" data-id="${a.id}"><span class="ofcn"><b>${esc(a.name)}</b>${sub ? `<small class="muted">${sub}</small>` : ''}<small class="agr-dl">${agrDeadline(a)}</small></span>${sum}${ic('chev', 's')}</button>${doc}${fold}</li>`;
}
function agrHtml() {
  if (AGR.oid !== OFC.info?.org_id) Object.assign(AGR, {oid: OFC.info?.org_id, data: null, err: null, opened: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only for admins of the office.')}</div>`;
  if (AGR.err) return `<div class="empty">${esc(AGR.err)}</div>`;
  if (!AGR.data) { setTimeout(() => { if (!AGR.data) agrLoad(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const items = AGR.data.items || [];
  const id = +S.route.id || 0;
  if (id && AGR.opened !== id) { AGR.opened = id; const a = items.find(x => x.id === id); if (a) setTimeout(() => agrModal(a), 0); }
  const bar = `<div class="ofcbar agr-bar"><h3 class="ofcgrp">${tr('Contracts & insurance')}</h3><span class="spacer"></span>
    <label class="chkl"><input type="checkbox" data-agr="arch" ${AGR.arch ? 'checked' : ''}><span>${tr('Show archived')}</span></label>
    <button class="btn sm pri" data-agr="new">${ic('plus', 's')}<span>${tr('New contract')}</span></button></div>`;
  if (!items.length) return bar + `<p class="muted lempty">${tr('No contracts yet, e.g. business liability insurance, office rent or a leasing contract.')}</p>`;
  const sumM = items.filter(a => !a.archived && a.monthly != null).reduce((s, a) => s + +a.monthly, 0);
  const groups = AGR_KINDS.map(([k, n]) => {
    const rows = items.filter(a => a.kind === k); if (!rows.length) return '';
    return `<h4 class="fcicat">${esc(tr(n))}</h4><ul class="ofclist" role="list">${rows.map(agrRow).join('')}</ul>`;
  }).join('');
  // 2.298.0 A2 (#3186): the rule of the last day to cancel behind (i) (here and at the notice period of the editor)
  return bar + groups + `<div class="muted ofchint">${esc(tr('Together {0} per month.', ofcMoney(sumM)))}<div class="shint">${esc(tr('The last day to cancel is the end of the term minus the notice period; a contract that renews rolls on to its next term.'))}</div></div>`;
}

// ---- the editor
function agrModal(a) {
  const L = AGR.data?.lists || [];
  const lid = a?.task?.list_id || L.find(l => l.inbox)?.id || '';
  const cov = a?.covered?.count ? `<p class="muted agr-cov">${esc(trn('Covers {0} device (new value {1})', 'Covers {0} devices (new value {1})', a.covered.count, ofcMoney(a.covered.new_value)))}</p>` : '';
  const renew = AGR_RENEW.includes(+(a?.renew_months ?? 12)) ? AGR_RENEW : [...AGR_RENEW, +a.renew_months].sort((x, y) => x - y);
  const rnName = m => !m ? tr('Ends without renewal') : m % 12 === 0 ? trn('By {0} year', 'By {0} years', m / 12) : trn('By {0} month', 'By {0} months', m);
  const md = modal(`<h3>${a ? tr('Edit contract') : tr('New contract')}</h3>
    ${ofcRowF('agr-kind', tr('Kind'), ofcSel('agr-kind', a?.kind || 'insurance', Object.entries(AGR_KIND1).map(([k, n]) => [k, tr(n)])))}
    ${ofcRowF('agr-name', tr('Name'), ofcIn('agr-name', a?.name, {ph: tr('e.g. Business liability insurance')}))}
    ${ofcRowF('agr-provider', tr('Provider'), ofcIn('agr-provider', a?.provider))}
    ${ofcRowF('agr-number', tr('Policy or contract number'), ofcIn('agr-number', a?.number, {max: 100}))}
    <div class="row agr-cost"><label for="agr-cost">${tr('Contribution')}</label>${ofcIn('agr-cost', a?.cost ? fmtNum(+a.cost, 2) : '', {num: true})}<span class="muted">${esc(ofcCur())}</span>${ofcSel('agr-per', a?.per || 'month', AGR_PERS.map(([k, n]) => [k, tr(n)]))}</div>
    ${ofcRowF('agr-vat', tr('VAT rate'), ofcSel('agr-vat', a?.vat_pct ?? '', [['19', '19 %'], ['7', '7 %'], ['0', '0 %']], tr('No VAT')), tr('With a VAT rate the contribution is net.'), {keep: 1})}
    <div class="row"><label id="agr-startl">${tr('Start|from')}</label>${dateIn('agr-start', a?.start || '', {label: tr('Start'), empty: tr('none')})}</div>
    <div class="row"><label id="agr-endsl">${tr('End of the current term')}</label>${dateIn('agr-ends', a?.ends || '', {label: tr('End of the current term'), empty: tr('open-ended'), after: 'agr-start'})}</div>
    <div class="row agr-notice"><label for="agr-notice">${tr('Notice period')}</label><input id="agr-notice" type="number" min="0" max="365" inputmode="numeric" value="${+(a?.notice ?? 3)}">${ofcSel('agr-nu', a?.notice_unit || 'm', AGR_UNITS.map(([k, n]) => [k, tr(n)]))}</div><div class="shint">${esc(tr('The last day to cancel is the end of the term minus the notice period; a contract that renews rolls on to its next term.'))}</div>
    ${ofcRowF('agr-renew', tr('Renews automatically'), ofcSel('agr-renew', a?.renew_months ?? 12, renew.map(m => [m, rnName(m)])))}
    <div class="row"><label for="agr-lead">${tr('Remind me days before')}</label><input id="agr-lead" type="number" min="0" max="365" inputmode="numeric" value="${+(a?.lead_days ?? 30)}"></div>
    <label class="chkl"><input type="checkbox" id="agr-cf" ${!a || a.cashflow ? 'checked' : ''}><span>${tr('Contribution in the cash flow')}</span></label>
    <label class="chkl"><input type="checkbox" id="agr-task" ${!a || a.task ? 'checked' : ''}><span>${tr('Deadline as a task')}</span></label>
    <div class="row agr-listrow"><label for="agr-list">${tr('Project')}</label><select id="agr-list">${L.map(l => `<option value="${l.id}" ${l.id === lid ? 'selected' : ''}>${esc(l.inbox ? tr('Basket') : l.name)}</option>`).join('')}</select></div>
    <p class="muted ofchint">${tr('One task due on the last day to cancel, repeating with the renewal.')}</p>
    <div class="row agr-docrow"><label>${tr('Document')}</label><span class="agr-docv"></span></div>
    ${ofcRowF('agr-note', tr('Note'), `<textarea id="agr-note" rows="2" maxlength="2000">${esc(a?.note || '')}</textarea>`)}
    ${cov}
    <div class="aerr" role="alert"></div>
    <div class="foot">${a ? `<button class="btn danger" data-m="del">${tr('Delete')}</button><button class="btn" data-m="arch">${a.archived ? tr('Restore') : tr('Archive')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${a ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg', 'agr-dlg');
  let doc = a?.doc || null;
  const drawDoc = () => {
    const el = $('.agr-docv', md); if (!el) return;
    el.innerHTML = (doc ? `<a href="#docs/${doc.id}" class="agr-docname">${ic('file', 's')} ${esc(doc.name)}</a><button type="button" class="btn sm ghost" data-m="docx">${tr('Remove')}</button>` : '')
      + `<button type="button" class="btn sm" data-m="docpick">${ic('search', 's')} ${tr('Choose')}</button><button type="button" class="btn sm" data-m="docup">${ic('upload', 's')} ${tr('Upload')}</button>`;
  };
  const listRow = () => { const on = $('#agr-task', md)?.checked; $('.agr-listrow', md)?.classList.toggle('hidden', !on); };
  drawDoc(); listRow();
  md.addEventListener('change', e => { if (e.target.id === 'agr-task') listRow(); });
  const close = fgModal(md);
  const v = id => $(id, md)?.value ?? '';
  const read = () => ({kind: v('#agr-kind'), name: v('#agr-name'), provider: v('#agr-provider'), number: v('#agr-number'), cost: ofcNum(v('#agr-cost')) ?? '',
    per: v('#agr-per'), vat_pct: v('#agr-vat') || null, start: v('#agr-start'), ends: v('#agr-ends'), notice: +v('#agr-notice') || 0, notice_unit: v('#agr-nu'),
    renew_months: +v('#agr-renew') || 0, lead_days: +v('#agr-lead') || 0, cashflow: $('#agr-cf', md)?.checked ? 1 : 0, task: $('#agr-task', md)?.checked ? 1 : 0,
    list_id: +v('#agr-list') || null, doc_node_id: doc?.id || null, note: v('#agr-note')});
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { close(); return; }
    if (m === 'docx') { doc = null; drawDoc(); return; }
    if (m === 'docpick') { agrDocPick(d => { doc = d; drawDoc(); }); return; }
    if (m === 'docup') { agrDocUpload(d => { doc = d; drawDoc(); }, $('.aerr', md)); return; }
    try {
      if (m === 'del') { await agrDelete(a); md.remove(); return; }
      if (m === 'arch') { await agrArchive(a, !a.archived); md.remove(); return; }
      await agrSave(a, read()); md.remove();
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}
const agrBody = a => ({kind: a.kind, name: a.name, provider: a.provider, number: a.number, cost: a.cost ?? '', per: a.per, vat_pct: a.vat_pct ?? null, start: a.start, ends: a.ends,
  notice: a.notice, notice_unit: a.notice_unit, renew_months: a.renew_months, lead_days: a.lead_days, cashflow: a.cashflow, task: a.task ? 1 : 0,
  list_id: a.task?.list_id || null, doc_node_id: a.doc_node_id || null, note: a.note});
async function agrSave(a, body) {
  if (!a) {
    const j = await api('POST', '/api/office/agreements', body); agrReload();
    offerUndo(tr('Added'), histAdd({label: tr('Contract added'), undo: async () => { await api('DELETE', `/api/office/agreements/${j.id}`); agrReload(); },
      redo: async () => { await api('POST', `/api/office/agreements/${j.id}/restore`, {}); agrReload(); }}));
    return j;
  }
  const old = agrBody(a);
  const j = await api('PATCH', `/api/office/agreements/${a.id}`, body); agrReload();
  offerUndo(tr('Saved'), histAdd({label: tr('Contract changed'), undo: async () => { await api('PATCH', `/api/office/agreements/${a.id}`, old); agrReload(); },
    redo: async () => { await api('PATCH', `/api/office/agreements/${a.id}`, body); agrReload(); }}));
  return j;
}
async function agrArchive(a, on) {
  await api('PATCH', `/api/office/agreements/${a.id}`, {archived: on ? 1 : 0}); agrReload();
  offerUndo(on ? tr('Archived') : tr('Restored'), histAdd({label: on ? tr('Contract archived') : tr('Contract restored'),
    undo: async () => { await api('PATCH', `/api/office/agreements/${a.id}`, {archived: on ? 0 : 1}); agrReload(); },
    redo: async () => { await api('PATCH', `/api/office/agreements/${a.id}`, {archived: on ? 1 : 0}); agrReload(); }}));
}
async function agrDelete(a) {
  if (!await askConfirm(tr('Delete “{0}”?', a.name), tr('The deadline task is ended, not deleted. You can undo this.'), {ok: tr('Delete'), danger: true})) return;
  await api('DELETE', `/api/office/agreements/${a.id}`); agrReload();
  offerUndo(tr('Deleted'), histAdd({label: tr('Contract deleted'), undo: async () => { await api('POST', `/api/office/agreements/${a.id}/restore`, {archived: a.archived ? 1 : 0}); agrReload(); },
    redo: async () => { await api('DELETE', `/api/office/agreements/${a.id}`); agrReload(); }}));
}

// ---- the document: one of the office's documents space (choose) or a new one (uploaded there, sealed like every document)
function agrDocPick(done) {
  const ws = AGR.data?.doc_ws || 'private';
  const md = modal(`<h3>${tr('Choose a document')}</h3><div class="row"><input id="agr-dq" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" maxlength="100"></div>
    <ul class="ofclist agr-docs" role="list"><li class="muted">${tr('Loading…')}</li></ul><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button></div>`);
  md.classList.add('ofcdlg');
  let seq = 0, docs = [];
  const load = async () => {
    const s = ++seq, q = $('#agr-dq', md)?.value.trim() || '';
    try { const j = await api('GET', `/api/docs?ws=${encodeURIComponent(ws)}&facets=0&limit=30${q ? '&q=' + encodeURIComponent(q) : ''}`); if (s !== seq) return; docs = j.docs || []; }
    catch (x) { if (s === seq) docs = []; }
    const ul = $('.agr-docs', md); if (!ul) return;
    ul.innerHTML = docs.length ? docs.map(d => `<li><button type="button" class="ofcrow" data-m="pick" data-id="${d.id}"><span class="ofcn"><b>${esc(d.name)}</b><small class="muted">${esc(fmtDateLoc((d.date || d.created_at || '').slice(0, 10)))}</small></span>${ic('chev', 's')}</button></li>`).join('')
      : `<li class="muted lempty">${tr('No documents found.')}</li>`;
  };
  let t = null;
  md.addEventListener('input', e => { if (e.target.id === 'agr-dq') { clearTimeout(t); t = setTimeout(load, 250); } });
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const d = docs.find(x => x.id === +b.dataset.id); if (d) { done({id: d.id, name: d.name}); md.remove(); }
  });
  load(); setTimeout(() => $('#agr-dq', md)?.focus(), 0);
}
function agrDocUpload(done, errEl) {
  const i = document.createElement('input'); i.type = 'file';
  i.onchange = async () => {
    const f = i.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('files', f); fd.append('ws', AGR.data?.doc_ws || 'private');
    try {
      const j = await api('POST', '/api/docs', fd);
      if (j.ids?.[0]) done({id: j.ids[0], name: f.name}); else if (errEl) errEl.textContent = (j.errors || []).join(' ');
    } catch (x) { if (errEl) errEl.textContent = x.message || ''; }
  };
  i.click();
}

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-agr]'); if (!b || b.tagName === 'INPUT') return;
  const k = b.dataset.agr;
  if (k === 'new') agrModal(null);
  else if (k === 'open') { const a = (AGR.data?.items || []).find(x => x.id === +b.dataset.id); if (a) agrModal(a); }
  else return;
  e.preventDefault();
});
document.addEventListener('change', e => {
  const t = e.target.closest?.('[data-agr="arch"]'); if (!t) return;
  AGR.arch = t.checked; AGR.data = null; ofcDraw();
});
// 2.351.0 B (#2749): a contract into a folder of the office's file tree (office_cfiles.js fsr_fileMenu)
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-agrfold]'); if (!b) return;
  const a = (AGR.data?.items || []).find(x => x.id === +b.dataset.agrfold); if (a) fsr_fileMenu(b, 'office_agreement', a.id, a.name);
});
