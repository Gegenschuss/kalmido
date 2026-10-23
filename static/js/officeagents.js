/* 2.51.0 A (#1348, #1350): agents in the office (Office & finance) -- drafts only, a person confirms.
   - the agent's switch "May draft office documents" in its settings dialog (admin of its office area; a personal office:
     the person), GET / PATCH /api/office/agents/<id>; the privacy switch of the area in the office settings (agents_read)
   - the marks of an agent's positions in the quotation editor (free / price changed / discount, accent + text) with
     "Confirm", "drafted by agent X" above the document
   - "Suggested payments" above the invoice list: an admin books (the normal payment) or rejects each one
   Classic script sharing the global scope with the others (load order: index.html). */
const OA = {pp: null, ppLoading: false};

// ---- the agent's switch (settings dialog of an agent: agentchat.js agModal, settings.js permissions of my agent)
const oa_switchRowHtml = aid => `<div class="oa_sw" data-oa-aid="${+aid}" hidden></div>`;
async function oa_switchLoad(md) {
  const box = md && $('[data-oa-aid]', md); if (!box) return;
  let j; try { j = await rawFetch('GET', `/api/office/agents/${box.dataset.oaAid}`); } catch { return; }  // not in my office area: nothing shown
  oa_switchDraw(box, j);
  box.addEventListener('change', async e => {
    const cb = e.target.closest('#oa-sw'); if (!cb) return;
    cb.disabled = true;
    try { const r = await api('PATCH', `/api/office/agents/${box.dataset.oaAid}`, {office_drafts: cb.checked}); j.office_drafts = r.office_drafts; toast(tr('Saved')); }
    catch { cb.checked = !cb.checked; }
    finally { oa_switchDraw(box, j); }
  });
}
function oa_switchDraw(box, j) {
  box.hidden = false;
  box.innerHTML = `<div class="row"><label>${tr('Office & finance')}</label><label class="chkl"><input type="checkbox" id="oa-sw" ${j.office_drafts ? 'checked' : ''} ${j.can_set ? '' : 'disabled'}> ${tr('May draft office documents')}</label></div>
    <div class="shint keep">${tr('Quotations, invoices and reminders as drafts and payment suggestions; never finalise, send, delete or book. Also needs the permission “Office drafts”.')}${j.can_set ? '' : ' ' + tr('Only an admin of its office can switch this.')}</div>
    ${j.office_drafts && !j.agents_read ? `<div class="shint keep warn">${tr('Off in the office settings: “Agents may read office data”.')}</div>` : ''}`;
}

// ---- the privacy switch of the office area (office.js settings form)
const oa_settingsHtml = (s, dis) => `<h3>${tr('Agents')}</h3>
  <div class="row"><label></label><label class="chkl"><input type="checkbox" id="os-agents-read" ${s.agents_read ? 'checked' : ''} ${dis}> ${tr('Agents may read office data')}</label></div>
  <div class="shint keep">${tr('Client and price data go to the AI model of the connected agent. Each agent also needs its own switch “May draft office documents”; every access is in the access log.')}</div>`;
const oa_settingsBody = form => ($('#os-agents-read', form) ? {agents_read: $('#os-agents-read', form).checked ? 1 : 0} : {});

// ---- the access log (office.js ofcLogHtml): the filter "Agents" and the names of what an agent did
const OA_LOG_TG = {office: N_('Office'), clients: N_('Clients'), docs: N_('Documents'), pdf: N_('PDF preview'), offer: N_('Quotation draft'),
  invoice: N_('Invoice draft'), reminder: N_('Reminder draft'), payment: N_('Payment suggestion'), agent: N_('Agent'), pay_prop: N_('Payment suggestion')};
const oa_logFilter = () => OFC.log.some(x => /^agent_/.test(x.action)) ? `<div class="seg oa_logf" role="group" aria-label="${esc(tr('Show'))}">${[['log-all', N_('All|entries'), !OFC.logAg], ['log-ag', N_('Agents'), !!OFC.logAg]].map(([k, n, on]) => `<button type="button" data-ofc="${k}" class="${on ? 'on' : ''}" aria-pressed="${on}">${tr(n)}</button>`).join('')}</div>` : '';

// ---- the marks of an agent's positions (office_docs.js editor)
const OA_FLAG = {free: N_('free'), price: N_('price changed'), discount: N_('discount')};
function oa_flagHtml(it, i) {
  if (!it.agent_flag) return '';
  const fs = it.agent_flag.split(',').filter(Boolean).map(f => { const [k, v] = f.split(':'); return k === 'discount' && v ? tr('discount {0} %', v) : tr(OA_FLAG[k] || k); });
  return `<span class="oa_flags" role="note"><span class="oa_flagt">${ic('bot', 's')} ${esc(fs.join(' · '))}</span><button type="button" class="btn sm" data-oa="confirm" data-i="${i}">${ic('check', 's')} ${tr('Confirm')}</button></span>`;
}
const oa_docBanner = d => d.agent_name ? `<div class="oa_by shint keep">${ic('bot', 's')} ${esc(tr('Drafted by the agent {0}', d.agent_name))}${(d.items || []).some(it => it.agent_flag) ? ' · ' + esc(tr('marked positions need your look')) : ''}${d.list_name ? ` · ${esc(tr('Project'))}: <a href="#l/${+d.list_id}">${esc(d.list_name)}</a>` : ''}</div>` : '';
document.addEventListener('click', e => {
  const b = e.target.closest('[data-oa="confirm"]'); if (!b || typeof OFD === 'undefined' || !OFD.doc) return;
  const it = ((typeof tpCur === 'function' ? tpCur() : OFD.doc).items || [])[+b.dataset.i]; if (!it) return;  // 2.113.0 (#2248): a mark inside an open part
  it.confirm = true; it.agent_flag = '';
  if (typeof ofdPutItems === 'function') Promise.resolve(ofdPutItems()).then(() => { if (typeof ofdDraw === 'function') ofdDraw(); });
});

// ---- #1350: suggested payments above the invoice list
function oa_ppBox() {
  if (!OA.pp) { if (!OA.ppLoading) setTimeout(oa_ppLoad, 0); return ''; }
  if (!OA.pp.items.length) return '';
  const conf = {high: N_('sure'), medium: N_('likely'), low: N_('unsure')};
  return `<section class="oa_pp" aria-label="${esc(tr('Suggested payments'))}"><h3>${ic('bot', 's')} ${tr('Suggested payments')}</h3><ul role="list">${OA.pp.items.map(p => `<li>
    <span class="oa_ppm"><b><a href="#office/offers/${+p.doc_id}">${esc(p.number || '#' + p.doc_id)}</a>${p.client_name ? ' · ' + esc(p.client_name) : ''}</b>
    <small class="muted">${esc([p.date ? new Date(p.date + 'T12:00').toLocaleDateString(LOCALE()) : '', p.reference, tr(conf[p.confidence] || p.confidence), p.agent_name].filter(Boolean).join(' · '))}</small></span>
    <b class="oa_ppa">${esc(fmtNum(+p.amount, 2))} ${esc(ofcSym(p.currency || 'EUR'))}</b>
    ${OA.pp.admin ? `<span class="oa_ppb"><button type="button" class="btn sm pri" data-oa="pp-ok" data-id="${p.id}">${ic('check', 's')} ${tr('Book')}</button><button type="button" class="btn sm" data-oa="pp-no" data-id="${p.id}">${tr('Reject')}</button></span>` : ''}</li>`).join('')}</ul>
    ${OA.pp.admin ? '' : `<p class="muted">${tr('An admin of the organisation books payments.')}</p>`}</section>`;
}
async function oa_ppLoad() {
  OA.ppLoading = true;
  try { OA.pp = await rawFetch('GET', '/api/office/pay-props'); } catch { OA.pp = {items: [], admin: false}; } finally { OA.ppLoading = false; }
  if (OA.pp.items.length && typeof ofdDraw === 'function') ofdDraw();
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-oa="pp-ok"], [data-oa="pp-no"]'); if (!b) return;
  b.disabled = true;
  try {
    await api('POST', `/api/office/pay-props/${+b.dataset.id}`, {action: b.dataset.oa === 'pp-ok' ? 'accept' : 'reject'});
    toast(b.dataset.oa === 'pp-ok' ? tr('Payment recorded') : tr('Rejected'));
    OA.pp = null; if (typeof OFD !== 'undefined') OFD.list = null;
    if (typeof ofdLoadList === 'function') ofdLoadList(true);
  } catch { b.disabled = false; }
});
