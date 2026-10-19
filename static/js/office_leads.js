// 2.94.0 A (#1930): leads before the sales pipeline -- the first column "Leads" of the pipeline (office_pipeline.js draws the
// board and the deal dialog and calls the lead* functions below): a lead shows its source, next step and follow-up day (the
// day come or past in the accent colour; sorted by follow-up day), the dialog has the lead's fields, "Convert into a client"
// (an existing client with the same e-mail / company is offered) and the toolbar "New lead" + "Import CSV" (preview, then
// take over; duplicates by e-mail skipped). Every change is one undo step. Server: kalmido/office/leads.py.
const LEAD_SRC = [['website', N_('Website')], ['referral', N_('Recommendation')], ['event', N_('Event|lead')], ['social', N_('Social media')],
  ['booking', N_('Appointment booking')], ['import', N_('Import')], ['agent', N_('Agent')], ['other', N_('Other')]];
const leadSrcName = k => { const s = LEAD_SRC.find(x => x[0] === k); return s ? tr(s[1]) : ''; };
const leadDue = x => !!x.follow_up && x.follow_up <= today();

function leadSort(its) {  // by follow-up day (none last), then the newest first
  return its.slice().sort((a, b) => (a.follow_up || '9999').localeCompare(b.follow_up || '9999') || b.id - a.id);
}
function leadBar() {
  const s = PPS.data?.summary || {};
  return `${s.leads ? `<span class="muted lead-cnt">${esc(trn('{0} lead', '{0} leads', s.leads))}${s.leads_due ? ` · <b class="lead-duen">${esc(tr('{0} to follow up', s.leads_due))}</b>` : ''}</span>` : ''}
    <button class="btn sm lead-tb" data-lead="import">${ic('upload', 's')}<span>${tr('Import CSV')}</span></button>
    <button class="btn sm lead-tb" data-pp="newlead">${ic('plus', 's')}<span>${tr('New lead')}</span></button>`;
}
function leadCard(x) {
  const who = [x.contact, x.company].filter(v => v && v !== x.title).join(' · ');
  const due = leadDue(x);
  return `<li><div role="button" tabindex="0" class="ppcard lead-card${due ? ' lead-due' : ''}" data-pp="open" data-id="${x.id}">
    <span class="pptitle">${esc(x.title)}</span>${who ? `<small class="muted">${esc(who)}</small>` : ''}
    ${x.next_step ? `<span class="lead-next">${ic('right', 's')}<span>${esc(x.next_step)}</span></span>` : ''}
    <span class="ppmeta">${x.follow_up ? `<span class="lead-fu${due ? ' due' : ''}">${ic('clock', 's')}<span>${esc(fmtDateLoc(x.follow_up))}</span></span>` : ''}${x.source ? `<span class="rotag">${esc(leadSrcName(x.source))}</span>` : ''}</span></div></li>`;
}
// the lead's rows of the deal dialog (shown while the stage is lead)
function leadFields(x, on) {
  return `<div class="leadf" ${on ? '' : 'hidden'}>
    ${ofcRowF('lead-company', tr('Company'), ofcIn('lead-company', x?.company))}
    ${ofcRowF('lead-email', tr('E-mail'), `<input id="lead-email" type="email" inputmode="email" autocomplete="off" maxlength="200" value="${esc(x?.email || '')}">`)}
    ${ofcRowF('lead-phone', tr('Phone'), `<input id="lead-phone" type="tel" inputmode="tel" autocomplete="off" maxlength="60" value="${esc(x?.phone || '')}">`)}
    ${ofcRowF('lead-source', tr('Source|lead'), ofcSel('lead-source', x?.source || '', LEAD_SRC.map(([k, n]) => [k, tr(n)]), tr('none')))}
    ${ofcRowF('lead-next', tr('Next step'), ofcIn('lead-next', x?.next_step, {max: 300, ph: tr('e.g. Call back and send the showreel')}))}
    <div class="row"><label id="lead-ful">${tr('Follow-up')}</label>${dateIn('lead-fu', x?.follow_up || '', {label: tr('Follow-up'), empty: tr('none')})}</div>
    ${x?.stage === 'lead' ? `<div class="ppacts"><button class="btn pri" data-m="convert">${ic('user', 's')}<span>${tr('Convert into a client')}</span></button></div>` : ''}</div>`;
}
function leadBody(md) {
  const v = id => $(id, md)?.value ?? '';
  return {company: v('#lead-company'), email: v('#lead-email').trim(), phone: v('#lead-phone'), source: v('#lead-source'), next_step: v('#lead-next'), follow_up: v('#lead-fu')};
}

// ---- convert into a client + deal (stage inquiry); the undo: back to lead, the new client removed again
async function leadConvert(x, md) {
  const j = await api('GET', `/api/office/deals/${x.id}/convert`);
  const go2 = async cid => {
    const r = await api('POST', `/api/office/deals/${x.id}/convert`, cid ? {client_id: cid} : {});
    md?.remove(); PPS.stage = 'inquiry'; pp_reload();
    if (typeof OFD === 'object') OFD.clients = null;
    toast(tr('Converted into a client: {0}', r.deal.client_name || ''), async () => { await api('POST', `/api/office/deals/${x.id}/unconvert`, {remove_client: !!r.client_new}); PPS.stage = 'lead'; pp_reload(); });
  };
  if (!(j.matches || []).length) return go2(null);
  const pick = modal(`<h3>${tr('Convert into a client')}</h3><p class="muted">${tr('There is already a client that fits this lead:')}</p>
    <ul class="ofclist lead-match" role="list">${j.matches.map(m => `<li><button class="btn lead-mbtn" data-lm="${m.id}">${ic('user', 's')}<span>${esc(cdn_label(m))}${m.email ? ` <small class="muted">${esc(m.email)}</small>` : ''}</span></button></li>`).join('')}</ul>
    <div class="foot"><span class="spacer"></span><button class="btn" data-lm="close">${tr('Cancel')}</button><button class="btn pri" data-lm="new">${tr('Add as new client')}</button></div>`);
  const close = fgModal(pick);
  pick.addEventListener('click', async e => {
    const b = e.target.closest('[data-lm]'); if (!b) return;
    const v = b.dataset.lm;
    if (v === 'close') { close(); return; }
    try { await go2(v === 'new' ? null : +v); pick.remove(); } catch (x2) { toast(x2.message || tr('unknown')); }
  });
}

// ---- CSV import: file -> preview -> take over (one undo step: the imported leads into the bin)
function leadPick() {
  const i = document.createElement('input'); i.type = 'file'; i.accept = '.csv,.txt,text/csv,text/plain';
  i.onchange = () => { if (i.files[0]) leadRead(i.files[0]); }; i.click();
}
async function leadRead(f) {
  const rd = enc => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => no(r.error); r.readAsText(f, enc); });
  let text;
  try { text = await f.text(); if (text.includes('�')) text = await rd('windows-1252'); } catch (x) { toast(x.message || tr('unknown')); return; }  // as the bank import
  let p;
  try { p = await api('POST', '/api/office/leads/import', {text}); } catch (x) { toast(x.message || tr('unknown')); return; }
  leadImpModal(text, p);
}
function leadImpModal(text, p) {
  const rows = p.rows || [];
  const li = x => `<li class="${x.error ? 'lead-err' : x.dup ? 'lead-dup' : ''}"><span class="pptitle">${esc(x.title || '–')}</span>
    <small class="muted">${esc([x.contact !== x.title ? x.contact : '', x.email, x.follow_up ? fmtDateLoc(x.follow_up) : ''].filter(Boolean).join(' · '))}</small>
    ${x.error ? `<small class="lead-why">${esc(x.error)}</small>` : x.dup ? `<small class="lead-why">${tr('Already there (same e-mail): skipped')}</small>` : ''}</li>`;
  const md = modal(`<h3>${tr('Import leads')}</h3>
    <p class="muted">${esc(tr('Columns found: {0}', Object.values(p.columns || {}).join(', ')))}</p>
    <p><b>${esc(trn('{0} lead', '{0} leads', p.count))}</b>${p.dup_count ? ` · ${esc(tr('{0} duplicates', p.dup_count))}` : ''}${p.skipped ? ` · ${esc(tr('{0} rows with errors', p.skipped))}` : ''}</p>
    <ul class="ofclist lead-pv" role="list">${rows.slice(0, 200).map(li).join('')}</ul>${rows.length > 200 ? `<p class="muted">${esc(trn('and {0} more', 'and {0} more', rows.length - 200))}</p>` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-li="close">${tr('Cancel')}</button><button class="btn pri" data-li="go" ${p.count ? '' : 'disabled'}>${esc(tr('Import {0}', p.count))}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-li]'); if (!b) return;
    if (b.dataset.li === 'close') { close(); return; }
    b.disabled = true;
    try {
      const j = await api('POST', '/api/office/leads/import', {text, commit: true});
      md.remove(); PPS.stage = 'lead'; pp_reload();
      toast(trn('{0} lead imported', '{0} leads imported', j.count), async () => { await api('POST', '/api/office/leads/import/undo', {ids: j.ids}); pp_reload(); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || tr('unknown'); b.disabled = false; }
  });
}

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-lead]'); if (!b) return;
  if (b.dataset.lead === 'import') { e.preventDefault(); leadPick(); }
});
