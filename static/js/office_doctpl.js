// 2.93.0 A (#1927): document templates and documents in the office (tab "Documents", admins of the office area only).
// Templates with {{variables}} (three samples in German / English to take over), documents made from them for a client
// (optionally a project list and a quotation of the client): a draft keeps the variables, the preview fills and marks them,
// "Finish" freezes the text and files the PDF with the client; a signable document gets a customer link (simple electronic
// signature, office/signoff.py). Server: kalmido/office/doctpl.py. The task templates (templates.js) are something else.
const DT = {data: null, undo: null, loading: false, err: null, view: 'docs', fClient: '', fList: '', fStatus: '', pv: null, pvSeq: 0, sg: null, oid: undefined, preset: null};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['gendocs', 'file', N_('Documents'), 1, () => dtTabHtml(), 'sell']);  // admins only; 'sell' = the group of 2.92.1's tab menu (#1917)
const DT_ST = {draft: N_('Draft'), final: N_('Finished'), signed: N_('Signed'), declined: N_('Declined')};
const dtReload = () => { DT.data = null; DT.pv = null; DT.sg = null; ofcDraw(); };
const dtDoc = id => (DT.data?.docs || []).find(d => d.id === id);
const dtTpl = id => (DT.data?.templates || []).find(t => t.id === id);
const dtStTag = d => `<span class="rotag dtp-st dtp-st-${esc(d.status)}">${esc(tr(DT_ST[d.status] || d.status))}</span>`;
const dtEsc = s => esc(s).replace(/\{\{([A-Za-z0-9_.]{1,40})\}\}/g, '<mark class="dtp-miss" title="' + esc(tr('No value')) + '">{{$1}}</mark>');

async function dtLoad() {
  if (DT.loading) return;
  DT.loading = true;
  try { DT.data = await api('GET', '/api/office/gen-docs'); DT.err = null; }
  catch (x) { DT.data = null; DT.err = x.message || tr('unknown'); }
  DT.loading = false;
  ofcDraw();
  if (DT.preset) { const p = DT.preset; DT.preset = null; dtNewModal(p); }
}
// the light markup (# heading, ## heading, - list, paragraphs) as HTML; missing variables marked
function dtBlocksHtml(blocks) {
  let out = '', ul = [];
  const flush = () => { if (ul.length) { out += `<ul>${ul.join('')}</ul>`; ul = []; } };
  for (const [k, t] of blocks || []) {
    if (k === 'li') { ul.push(`<li>${dtEsc(t)}</li>`); continue; }
    flush();
    out += k === 'h1' ? `<h3>${dtEsc(t)}</h3>` : k === 'h2' ? `<h4>${dtEsc(t)}</h4>` : `<p>${t.split('\n').map(dtEsc).join('<br>')}</p>`;
  }
  flush();
  return out;
}
function dtBlocks(text) {  // the same rules as doctpl.py dt_blocks (for the frozen text of a finished document)
  const out = [], para = [];
  const flush = () => { if (para.length) { out.push(['p', para.join('\n')]); para.length = 0; } };
  for (const ln of String(text || '').split('\n')) {
    const s = ln.trim();
    if (!s) flush();
    else if (s.startsWith('## ')) { flush(); out.push(['h2', s.slice(3).trim()]); }
    else if (s.startsWith('# ')) { flush(); out.push(['h1', s.slice(2).trim()]); }
    else if (s.startsWith('- ') || s.startsWith('* ')) { flush(); out.push(['li', s.slice(2).trim()]); }
    else para.push(s);
  }
  flush();
  return out;
}
// 2.114.4 C (#2278): the page preview (PDF, like the quotations) as a prominent button above the quick text preview
const dtPvBtn = id => `<button type="button" class="btn pri dtp-pvbtn" data-dt="pvpdf" data-id="${id}">${ic('eye', 's')}<span>${esc(tr('Preview (PDF)'))}</span></button>`;
async function dtPdfPreview(d) {
  if (!await dtSave(d, true)) return;
  const u = `/api/office/gen-docs/${d.id}/pdf`;
  typeof pdfView === 'function' ? pdfView({url: u, name: (d.title || 'document') + '.pdf', dlUrl: u}) : window.open(u, '_blank', 'noopener');
}
const dtVarBar = target => `<div class="dtp-vars" role="group" aria-label="${esc(tr('Insert a variable'))}">${(DT.data?.vars || []).map(v => `<button type="button" class="btn sm ghost" data-dt="var" data-k="${esc(v.key)}" data-t="${target}" title="{{${esc(v.key)}}}">${ic('plus', 's')}<span>${esc(v.label)}</span></button>`).join('')}</div>`;
const dtHint = () => `<p class="muted ofchint">${esc(tr('Headings start with #, list items with -. Variables are filled from the client, project, quotation and your company.'))}</p>`;

// ---- the tab
function dtTabHtml() {
  if (DT.oid !== OFC.info?.org_id) Object.assign(DT, {oid: OFC.info?.org_id, data: null, err: null, pv: null, sg: null, fClient: '', fList: '', fStatus: ''});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see documents and templates.')}</div>`;
  if (DT.err) return `<div class="empty">${esc(DT.err)}</div>`;
  if (!DT.data) { if (!DT.loading) setTimeout(dtLoad, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const id = S.route.tab === 'gendocs' ? S.route.id : null;
  if (id) { const d = dtDoc(id); return d ? dtDocHtml(d) : `<div class="empty">${tr('This document does not exist or you cannot see it.')}</div>`; }
  const seg = `<div class="seg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-dt="view" data-v="docs" class="${DT.view === 'docs' ? 'on' : ''}" aria-pressed="${DT.view === 'docs'}">${tr('Documents')}</button><button type="button" data-dt="view" data-v="templates" class="${DT.view === 'templates' ? 'on' : ''}" aria-pressed="${DT.view === 'templates'}">${tr('Templates')}</button></div>`;
  return DT.view === 'templates' ? dtTplsHtml(seg) : dtDocsHtml(seg);
}
function dtDocsHtml(seg) {
  const d = DT.data, f = x => (d.docs || []).filter(x);
  const docs = f(x => (!DT.fClient || x.client_id === +DT.fClient) && (!DT.fList || x.list_id === +DT.fList) && (!DT.fStatus || x.status === DT.fStatus));
  const lists = (d.lists || []).filter(l => (d.docs || []).some(x => x.list_id === l.id));
  const bar = `<div class="ofcbar dtp-bar">${seg}
    <select id="dt-fc" aria-label="${esc(tr('Client'))}"><option value="">${tr('All clients')}</option>${(d.clients || []).map(c => `<option value="${c.id}" ${String(c.id) === DT.fClient ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select>
    ${lists.length ? `<select id="dt-fl" aria-label="${esc(tr('Project'))}"><option value="">${tr('All projects')}</option>${lists.map(l => `<option value="${l.id}" ${String(l.id) === DT.fList ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select>` : ''}
    <select id="dt-fs" aria-label="${esc(tr('Status'))}"><option value="">${tr('All states')}</option>${Object.entries(DT_ST).map(([k, n]) => `<option value="${k}" ${k === DT.fStatus ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>
    <span class="spacer"></span><button class="btn sm pri" data-dt="new">${ic('plus', 's')}<span>${tr('New document')}</span></button></div>`;
  if (!docs.length) return bar + `<div class="empty nempty eact">${ic('file')}<span>${(d.docs || []).length ? tr('No documents match the filter.') : (d.templates || []).length ? tr('No documents yet. Create one from a template for a client.') : tr('No documents yet. Start with a template: take over a sample under Templates.')}</span>${!(d.templates || []).length ? `<button class="btn" data-dt="view" data-v="templates">${tr('Templates')}</button>` : ''}</div>`;
  return bar + `<ul class="ofclist dtp-list" role="list">${docs.map(x => `<li><button type="button" class="ofcrow" data-dt="open" data-id="${x.id}"><span class="ofcn"><b>${esc(x.title || x.kind_label)}</b>
    <small class="muted">${esc([cdn_name(x.client_id, x.client_name), x.list_name, x.kind_label, fmtDateLoc((x.final_at || x.created_at || '').slice(0, 10))].filter(Boolean).join(' · '))}</small></span>${dtStTag(x)}${ic('chev', 's')}</button></li>`).join('')}</ul>`;
}
function dtTplsHtml(seg) {
  const ts = DT.data.templates || [];
  const bar = `<div class="ofcbar dtp-bar">${seg}<span class="spacer"></span><button class="btn sm" data-dt="starters">${ic('copy', 's')}<span>${tr('Use sample')}</span></button><button class="btn sm pri" data-dt="tnew">${ic('plus', 's')}<span>${tr('New template')}</span></button></div>`;
  const rows = ts.map(t => `<li><button type="button" class="ofcrow" data-dt="topen" data-id="${t.id}"><span class="ofcn"><b>${esc(t.name)}</b><small class="muted">${esc([t.kind_label, (t.lang || '').toUpperCase(), t.sign ? tr('can be signed') : ''].filter(Boolean).join(' · '))}</small></span>${ic('chev', 's')}</button></li>`).join('');
  return bar + (rows ? `<ul class="ofclist dtp-list" role="list">${rows}</ul>` : `<div class="empty nempty eact">${ic('file')}<span>${tr('No templates yet. Take over a sample (letter, reminder, contract and more) and adapt it.')}</span><button class="btn pri" data-dt="starters">${tr('Use sample')}</button></div>`)
    + `<p class="muted ofchint">${esc(tr('These templates are for documents. Task templates stay in the lists.'))}</p>`;
}
function dtDocHtml(d) {
  const draft = d.status === 'draft', back = `<button class="btn sm ghost" data-dt="back">${ic('back', 's')}<span>${tr('All documents')}</span></button>`;
  const pdf = `/api/office/gen-docs/${d.id}/pdf`, spdf = pdf + '?signed=1';
  const pdfBtn = (u, label) => `<a class="btn sm" href="${u}" download data-dt="pdf"${typeof pv_attr === 'function' ? pv_attr({url: u, name: (d.title || 'document') + '.pdf', dlUrl: u}) : ''}>${ic('pdf', 's')}<span>${esc(label)}</span></a>`;
  const meta = [d.client_name ? `${ic('brief', 's')} <a href="#client/${d.client_id}">${esc(cdn_name(d.client_id, d.client_name))}</a>` : '', d.list_id ? `${ic('list', 's')} <a href="#l/${d.list_id}">${esc(d.list_name || tr('Project'))}</a>` : '',
    d.doc_id ? `${ic('receipt', 's')} <a href="#office/offers/${d.doc_id}">${esc(d.offer_number || tr('Quotation'))}</a>` : '', esc(d.kind_label)].filter(Boolean).join('<span class="muted"> · </span>');
  const head = `<div class="ofcbar">${back}<span class="spacer"></span>${draft ? '' : pdfBtn(pdf, 'PDF')}${d.status === 'signed' ? pdfBtn(spdf, tr('Signed PDF')) : ''}<button class="iconbtn" data-dt="more" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>
    <div class="dtp-head"><h3>${esc(d.title || d.kind_label)} ${dtStTag(d)}</h3><p class="dtp-meta">${meta}</p></div>`;
  if (draft) {
    const pv = DT.pv && DT.pv.id === d.id ? DT.pv : null;
    if (!pv) setTimeout(() => dtPreview(d.id), 0);
    return head + `<div class="dtp-edit">
      <div class="dtp-form">${ofcRowF('dt-title', tr('Title'), ofcIn('dt-title', d.title, {max: 300}))}
        ${dtRefsHtml(d.client_id, d.list_id, d.doc_id)}
        ${ofcChk('dt-sign', tr('The customer can sign it through a link'), d.sign)}
        <label for="dt-body" class="dtp-lab">${tr('Text')}</label>${dtVarBar('dt-body')}<textarea id="dt-body" class="dtp-ta" rows="16" maxlength="60000" spellcheck="true">${esc(d.body || '')}</textarea>${dtHint()}
        <div class="aerr" role="alert" id="dt-err"></div>
        <div class="foot dtp-acts"><button class="btn danger ghost" data-dt="arch" data-id="${d.id}">${ic('archive', 's')}<span>${tr('Archive')}</span></button><span class="spacer"></span>
          <button class="btn" data-dt="save" data-id="${d.id}">${tr('Save')}</button><button class="btn pri" data-dt="final" data-id="${d.id}">${ic('check', 's')}<span>${tr('Finish')}</span></button></div></div>
      <section class="dtp-pv" aria-label="${esc(tr('Preview'))}"><h4 class="muted">${tr('Preview')}</h4>${dtPvBtn(d.id)}${pv ? `${pv.missing.length ? `<p class="dtp-warn" role="status">${esc(tr('Without a value (stays empty in the PDF): {0}', pv.missing.map(k => '{{' + k + '}}').join(', ')))}</p>` : ''}<div class="dtp-doc">${dtBlocksHtml(pv.blocks)}</div>` : `<p class="muted">${tr('Loading…')}</p>`}</section></div>`;
  }
  const sg = d.sign && d.status !== 'draft' ? dtSigHtml(d) : '';
  return head + `<div class="dtp-doc dtp-final">${dtBlocksHtml(dtBlocks(d.body))}</div>
    <p class="muted ofchint">${esc(tr('Finished on {0}. The text is frozen (SHA-256 {1}…); for a new version edit a copy.', fmtWhen(d.final_at || d.updated_at), (d.body_hash || '').slice(0, 16)))}</p>
    <div class="ofcbar"><button class="btn sm" data-dt="copy" data-id="${d.id}">${ic('copy', 's')}<span>${tr('Edit a copy')}</span></button>${d.node_id ? `<a class="btn sm ghost" href="#docs/${d.node_id}">${ic('file', 's')}<span>${tr('In the documents')}</span></a>` : ''}</div>${sg}`;
}
function dtRefsHtml(cid, lid, did) {
  const d = DT.data, offers = (d.offers || []).filter(o => o.client_id === +cid);
  return `${ofcRowF('dt-client', tr('Client'), ofcSel('dt-client', cid || '', (d.clients || []).map(c => [c.id, cdn_label(c)]), tr('Choose a client')))}
    ${ofcRowF('dt-list', tr('Project'), ofcSel('dt-list', lid || '', (d.lists || []).map(l => [l.id, l.name]), tr('none')))}
    ${ofcRowF('dt-offer', tr('Quotation'), ofcSel('dt-offer', did || '', offers.map(o => [o.id, [o.number || tr('Draft'), o.project_title].filter(Boolean).join(' · ')]), tr('none')))}`;
}
async function dtPreview(id, bodyText) {
  const seq = ++DT.pvSeq, d = dtDoc(id); if (!d) return;
  const v = sel => $(sel)?.value;
  const b = {gen_doc_id: id};
  if (bodyText != null) Object.assign(b, {body: bodyText, client_id: +v('#dt-client') || null, list_id: +v('#dt-list') || null, doc_id: +v('#dt-offer') || null});
  try {
    const j = await api('POST', '/api/office/gen-docs/preview', b);
    if (seq !== DT.pvSeq) return;
    DT.pv = {id, ...j};
  } catch (x) { if (seq === DT.pvSeq) DT.pv = {id, missing: [], blocks: [['p', x.message || tr('unknown')]]}; }
  const box = $('.dtp-pv');
  if (box && bodyText != null) {  // only the preview pane (the text field keeps focus and cursor)
    const pv = DT.pv;
    box.innerHTML = `<h4 class="muted">${tr('Preview')}</h4>${dtPvBtn(id)}${pv.missing.length ? `<p class="dtp-warn" role="status">${esc(tr('Without a value (stays empty in the PDF): {0}', pv.missing.map(k => '{{' + k + '}}').join(', ')))}</p>` : ''}<div class="dtp-doc">${dtBlocksHtml(pv.blocks)}</div>`;
  } else ofcDraw();
}
let dtPvTimer = null;
const dtPvSoon = id => { clearTimeout(dtPvTimer); dtPvTimer = setTimeout(() => dtPreview(id, $('#dt-body')?.value ?? ''), 500); };

// ---- signature by the customer (link)
function dtSigHtml(d) {
  if (!DT.sg || DT.sg.id !== d.id) { setTimeout(() => dtSigLoad(d.id), 0); return `<section class="ofdsec dtp-sg"><h3>${tr('Signature by the customer')}</h3><p class="muted">${tr('Loading…')}</p></section>`; }
  const rows = DT.sg.rows, live = rows.some(x => x.live), can = d.status === 'final' && !d.archived;
  const st = x => x.revoked_at && x.state === 'open' ? tr('Stopped') : !x.live && x.state === 'open' ? tr('Expired') : x.state === 'accepted' ? tr('Signed') : x.state === 'declined' ? tr('Declined') : tr('Waiting for the customer');
  const row = x => `<li class="sgrow st-${esc(x.state)}"><div class="sghead"><b>${esc(st(x))}</b><small class="muted"> · ${esc(fmtWhen(x.created_at))}</small></div>
    ${x.live && x.url ? `<div class="row icalrow"><input readonly value="${esc(x.url)}" aria-label="${esc(tr('Signature link'))}" data-dturl="${x.id}"><button type="button" class="btn sm pri" data-dt="sgcopy" data-id="${x.id}">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm danger" data-dt="sgstop" data-id="${x.id}">${tr('Stop')}</button></div>` : ''}
    ${x.state !== 'open' ? `<div class="sgproto">${esc([x.signer_name, x.signer_email].filter(Boolean).join(' · '))}<br>${esc(fmtWhen(x.signed_at))} · ${esc(tr('Address {0}', x.ip || '?'))}${x.reason ? `<br>${esc(tr('Reason: {0}', x.reason))}` : ''}<br><small class="muted">SHA-256 ${esc(x.doc_hash || '')}</small></div>` : ''}</li>`;
  return `<section class="ofdsec dtp-sg"><h3>${tr('Signature by the customer')}</h3>${rows.length ? `<ul class="sglist" role="list">${rows.map(row).join('')}</ul>` : ''}
    ${can ? `<div class="row"><label for="dt-exp">${tr('Valid until')}</label>${dateIn('dt-exp', '', {min: today(), label: tr('Valid until'), empty: tr('no expiry')})}</div>
    <div class="row"><button type="button" class="btn sm ${live ? '' : 'pri'}" data-dt="sgnew" data-id="${d.id}">${ic('link', 's')} ${live ? tr('New signature link') : tr('Create signature link')}</button></div>` : ''}
    <div class="shint">${esc(typeof sg_note === 'function' ? sg_note() : '')}</div><div class="aerr" role="alert" id="dt-sgerr"></div></section>`;
}
async function dtSigLoad(id) {
  try { DT.sg = {id, rows: (await api('GET', `/api/office/gen-docs/${id}/signoffs`)).signoffs || []}; } catch { DT.sg = {id, rows: []}; }
  ofcDraw();
}

// ---- dialogs
function dtNewModal(p = {}) {
  const d = DT.data, ts = d.templates || [];
  if (!(d.clients || []).length) { toast(tr('Create a client first.')); return; }
  const tid = p.template_id || (p.kind ? ts.find(t => t.kind === p.kind)?.id : null) || ts[0]?.id || '';
  const md = modal(`<h3>${tr('New document')}</h3>
    ${ofcRowF('dt-tpl', tr('Template'), ofcSel('dt-tpl', tid, ts.map(t => [t.id, `${t.name} · ${t.kind_label}`]), tr('empty document')))}
    ${!ts.length ? `<p class="muted ofchint">${esc(tr('No templates yet. Take over a sample under Templates.'))}</p>` : ''}
    ${dtRefsHtml(p.client_id || '', p.list_id || '', p.doc_id || '')}
    ${ofcRowF('dt-ntitle', tr('Title'), ofcIn('dt-ntitle', p.title || '', {max: 300, ph: tr('as the template')}))}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Create')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('change', e => { if (e.target.id === 'dt-client') { const box = $('#dt-offer', md); const offers = (d.offers || []).filter(o => o.client_id === +e.target.value); box.innerHTML = `<option value="">${esc(tr('none'))}</option>` + offers.map(o => `<option value="${o.id}">${esc([o.number || tr('Draft'), o.project_title].filter(Boolean).join(' · '))}</option>`).join(''); } });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const v = s => $(s, md)?.value ?? '';
    try {
      const j = await api('POST', '/api/office/gen-docs', {template_id: +v('#dt-tpl') || null, client_id: +v('#dt-client') || null, list_id: +v('#dt-list') || null, doc_id: +v('#dt-offer') || null, title: v('#dt-ntitle')});
      md.remove(); DT.data = null; DT.pv = null; go(`office/gendocs/${j.id}`);
      toast(tr('Created'), async () => { await api('DELETE', `/api/office/gen-docs/${j.id}`); DT.data = null; go('office/gendocs'); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
// from a quotation (office_docs.js, menu "Create order confirmation"): the dialog with client + quotation set
function dtFromOffer(o) {
  DT.preset = {client_id: o.client_id, doc_id: o.id, list_id: o.list_id || '', kind: 'confirmation'};
  DT.view = 'docs'; DT.data = null;
  go('office/gendocs');
}
function dtTplModal(t) {
  const d = DT.data;
  const md = modal(`<h3>${t ? tr('Edit template') : tr('New template')}</h3>
    ${ofcRowF('dt-tname', tr('Name'), ofcIn('dt-tname', t?.name, {max: 200}))}
    ${ofcRowF('dt-tkind', tr('Kind'), ofcSel('dt-tkind', t?.kind || 'contract', (d.kinds || []).map(k => [k.key, k.label])))}
    ${ofcRowF('dt-tlang', tr('Language'), ofcSel('dt-tlang', t?.lang || d.lang || 'de', [['de', 'Deutsch'], ['en', 'English']]))}
    ${ofcChk('dt-tsign', tr('Documents from it can be signed by the customer'), t ? t.sign : 1)}
    <label for="dt-tbody" class="dtp-lab">${tr('Text')}</label>${dtVarBar('dt-tbody')}<textarea id="dt-tbody" class="dtp-ta" rows="14" maxlength="60000">${esc(t?.body || '')}</textarea>${dtHint()}
    <p class="muted ofchint">${esc(d.note || tr('Sample text, no legal advice.'))}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot">${t ? `<button class="btn danger" data-m="del">${tr('Archive')}</button>` : `<button class="btn" data-m="starters">${ic('copy', 's')}<span>${tr('Start from a sample')}</span></button>`}${t && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? `<button class="btn" data-m="move">${ic('brief', 's')} ${tr('Move to another workspace…')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${t ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg', 'dtp-dlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'starters') { md.remove(); dtStartersModal(); return; }  // 2.117.0 B (#2283)
    try {
      if (b.dataset.m === 'move') {  // 2.97.0 C (#2049)
        md.remove(); ofm_move({what: 'templates', ids: [t.id], from: ofm_officeFrom(), label: qn(t.name), after: async () => dtReload()});
        return;
      }
      if (b.dataset.m === 'del') {
        await api('DELETE', `/api/office/doc-templates/${t.id}`); md.remove(); dtReload();
        toast(tr('Archived'), async () => { await api('POST', `/api/office/doc-templates/${t.id}/restore`); dtReload(); });
        return;
      }
      const v = s => $(s, md)?.value ?? '';
      const body = {name: v('#dt-tname'), kind: v('#dt-tkind'), lang: v('#dt-tlang'), sign: $('#dt-tsign', md).checked ? 1 : 0, body: v('#dt-tbody')};
      if (t) {
        const old = {name: t.name, kind: t.kind, lang: t.lang, sign: t.sign, body: t.body};
        await api('PATCH', `/api/office/doc-templates/${t.id}`, body); md.remove(); dtReload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/doc-templates/${t.id}`, old); dtReload(); });
      } else {
        const j = await api('POST', '/api/office/doc-templates', body); md.remove(); dtReload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/doc-templates/${j.id}`); dtReload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function dtStartersModal() {
  let j;
  try { j = await api('GET', '/api/office/doc-templates/starters'); } catch (x) { toast(x.message || ''); return; }
  const md = modal(`<h3>${tr('Use sample')}</h3><p class="muted">${esc(j.note || '')}</p>
    ${ofcRowF('dt-slang', tr('Language'), ofcSel('dt-slang', j.lang, [['de', 'Deutsch'], ['en', 'English']]))}
    <ul class="ofclist dtp-starters" role="list">${j.starters.map(s => `<li><div class="ofcrow dtp-srow"><span class="ofcn"><b>${esc(s.name)}</b><small class="muted">${esc([s.kind !== 'other' ? s.kind_label : '', s.legal ? tr('Legal text: please have it checked') : ''].filter(Boolean).join(' · '))}</small></span><button type="button" class="btn sm pri" data-m="take" data-k="${esc(s.key)}">${tr('Take over')}</button></div></li>`).join('')}</ul>
    <div class="aerr" role="alert"></div><div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      const t = await api('POST', '/api/office/doc-templates', {starter: b.dataset.k, lang: $('#dt-slang', md).value});
      md.remove(); DT.view = 'templates'; dtReload();
      toast(tr('Template “{0}” added', t.name), async () => { await api('DELETE', `/api/office/doc-templates/${t.id}`); dtReload(); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
function dtInsertVar(btn) {
  const ta = document.getElementById(btn.dataset.t); if (!ta) return;
  const k = btn.dataset.k, a = ta.selectionStart ?? ta.value.length, z = ta.selectionEnd ?? a;
  // 2.114.4 C (#2280): spaced from the text around it; an address variable gets its own line
  const pre = ta.value.slice(0, a), post = ta.value.slice(z), line = /address$/.test(k);
  const lead = !pre || (line ? /\n$/ : /\s$/).test(pre) ? '' : line ? '\n' : ' ';
  const trail = !post || (line ? /^\n/ : /^\s/).test(post) ? '' : line ? '\n' : ' ';
  const ins = lead + `{{${k}}}` + trail;
  ta.focus();
  ta.setRangeText(ins, a, z, 'end');
  ta.setSelectionRange(a + lead.length + k.length + 4, a + lead.length + k.length + 4);
  ta.dispatchEvent(new Event('input', {bubbles: true}));
}
const dtDraftBody = () => ({title: $('#dt-title')?.value ?? '', body: $('#dt-body')?.value ?? '', client_id: +$('#dt-client')?.value || null, list_id: +$('#dt-list')?.value || null,
  doc_id: +$('#dt-offer')?.value || null, sign: $('#dt-sign')?.checked ? 1 : 0});
// a draft saves itself shortly after typing (quiet: the text field stays as it is; a redraw then shows the saved text);
// "Save" saves at once with an undo step back to the state the document was opened with
async function dtSave(d, quiet) {
  if (!$('#dt-body')) return true;
  const body = dtDraftBody(), old = DT.undo && DT.undo.id === d.id ? DT.undo.v : {title: d.title, body: d.body, client_id: d.client_id, list_id: d.list_id, doc_id: d.doc_id, sign: d.sign};
  const same = ['title', 'body', 'client_id', 'list_id', 'doc_id', 'sign'].every(k => (body[k] ?? null) === (d[k] ?? null));
  try {
    if (!same) Object.assign(d, await api('PATCH', `/api/office/gen-docs/${d.id}`, body));
    if (!quiet) { DT.undo = null; toast(tr('Saved'), async () => { await api('PATCH', `/api/office/gen-docs/${d.id}`, old); dtReload(); }); }
    else if (!same && !(DT.undo && DT.undo.id === d.id)) DT.undo = {id: d.id, v: old};
    const el = $('#dt-err'); if (el) el.textContent = '';
    return true;
  } catch (x) { const el = $('#dt-err'); if (el) el.textContent = x.message || ''; return false; }
}
let dtSaveTimer = null;
const dtSaveSoon = id => { clearTimeout(dtSaveTimer); dtSaveTimer = setTimeout(() => { const d = dtDoc(id); if (d && d.status === 'draft' && S.route.id === id) dtSave(d, true); }, 1500); };

// ---- events
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-dt]'); if (!b || b.tagName === 'INPUT' || b.tagName === 'SELECT') return;
  const a = b.dataset.dt, d = S.route.id ? dtDoc(S.route.id) : null;
  if (a === 'pdf') return;  // the link itself (download / preview)
  e.preventDefault();
  if (a === 'view') { DT.view = b.dataset.v; if (S.route.id) go('office/gendocs'); else ofcDraw(); }
  else if (a === 'new') dtNewModal();
  else if (a === 'open') { DT.pv = null; DT.sg = null; DT.undo = null; go(`office/gendocs/${b.dataset.id}`); }
  else if (a === 'back') { if (d && d.status === 'draft') { clearTimeout(dtSaveTimer); await dtSave(d, true); } go('office/gendocs'); }
  else if (a === 'tnew') dtTplModal(null);
  else if (a === 'topen') { const t = dtTpl(+b.dataset.id); if (t) dtTplModal(t); }
  else if (a === 'starters') dtStartersModal();
  else if (a === 'var') dtInsertVar(b);
  else if (a === 'pvpdf' && d) dtPdfPreview(d);
  else if (a === 'save' && d) dtSave(d);
  else if (a === 'final' && d) {
    if (!await dtSave(d, true)) return;
    // 2.114.4 C (#2281): empty variables are named before the text is frozen (the server preview of the saved draft)
    let miss = [];
    try { miss = (await api('POST', '/api/office/gen-docs/preview', {gen_doc_id: d.id})).missing || []; } catch {}
    if (miss.length && !await askConfirm(tr('Finish this document?'), tr('Without a value (stays empty in the PDF): {0}', miss.map(k => '{{' + k + '}}').join(', ')), {ok: tr('Continue'), cancel: tr('Back')})) return;
    if (!await askConfirm(tr('Finish this document?'), tr('The variables are filled in, the text is frozen and the PDF is filed with the client. Afterwards it can only be copied.'), {ok: tr('Finish')})) return;
    try { await api('POST', `/api/office/gen-docs/${d.id}/final`); toast(tr('Finished and filed')); dtReload(); } catch (x) { toast(x.message || tr('unknown')); }
  } else if (a === 'arch' && d) {
    try { await api('DELETE', `/api/office/gen-docs/${d.id}`); DT.data = null; go('office/gendocs'); toast(tr('Archived'), async () => { await api('POST', `/api/office/gen-docs/${d.id}/restore`); DT.data = null; go(`office/gendocs/${d.id}`); }); } catch (x) { toast(x.message || tr('unknown')); }
  } else if (a === 'copy' && d) {
    try { const j = await api('POST', '/api/office/gen-docs', {copy_of: d.id}); DT.data = null; DT.pv = null; go(`office/gendocs/${j.id}`); toast(tr('Copy created'), async () => { await api('DELETE', `/api/office/gen-docs/${j.id}`); DT.data = null; go(`office/gendocs/${d.id}`); }); } catch (x) { toast(x.message || tr('unknown')); }
  } else if (a === 'more' && d) {
    menu(b, [
      d.status !== 'draft' ? {label: tr('Edit a copy'), icon: 'copy', fn: () => b.closest('#view')?.querySelector('[data-dt="copy"]')?.click()} : null,
      d.status === 'draft' ? {label: tr('Preview (PDF)'), icon: 'eye', fn: () => dtPdfPreview(d)} : null,
      {label: tr('Archive'), icon: 'archive', cls: 'danger', fn: async () => {
        try { await api('DELETE', `/api/office/gen-docs/${d.id}`); DT.data = null; go('office/gendocs'); toast(tr('Archived'), async () => { await api('POST', `/api/office/gen-docs/${d.id}/restore`); DT.data = null; go(`office/gendocs/${d.id}`); }); } catch (x) { toast(x.message || tr('unknown')); }
      }}]);
  } else if (a === 'sgnew' && d) {
    const err = $('#dt-sgerr'); if (err) err.textContent = '';
    try {
      const j = await api('POST', `/api/office/gen-docs/${d.id}/signoff`, {expires: $('#dt-exp')?.value || null});
      DT.sg = null; ofcDraw();
      toast(tr('Signature link created'), async () => { await api('POST', `/api/office/signoffs/${j.id}/revoke`); DT.sg = null; ofcDraw(); });
    } catch (x) { if (err) err.textContent = x.message || ''; }
  } else if (a === 'sgcopy') {
    const i = $(`[data-dturl="${b.dataset.id}"]`);
    try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); }
  } else if (a === 'sgstop') {
    if (!await askConfirm(tr('Stop the signature link?'), tr('It stops working at once.'), {ok: tr('Stop'), danger: true})) return;
    try { await api('POST', `/api/office/signoffs/${b.dataset.id}/revoke`); toast(tr('Signature link stopped')); DT.sg = null; ofcDraw(); } catch (x) { toast(x.message || tr('unknown')); }
  }
});
document.addEventListener('change', e => {
  const x = e.target, id = x.id;
  if (id === 'dt-fc') { DT.fClient = x.value; ofcDraw(); }
  else if (id === 'dt-fl') { DT.fList = x.value; ofcDraw(); }
  else if (id === 'dt-fs') { DT.fStatus = x.value; ofcDraw(); }
  else if (S.route.mod === 'office' && S.route.tab === 'gendocs' && S.route.id && ['dt-client', 'dt-list', 'dt-offer'].includes(id) && !x.closest('.modal')) {
    if (id === 'dt-client') { const box = $('#dt-offer'); const offers = (DT.data?.offers || []).filter(o => o.client_id === +x.value); if (box) box.innerHTML = `<option value="">${esc(tr('none'))}</option>` + offers.map(o => `<option value="${o.id}">${esc([o.number || tr('Draft'), o.project_title].filter(Boolean).join(' · '))}</option>`).join(''); }
    dtPvSoon(S.route.id); dtSaveSoon(S.route.id);
  } else if (S.route.mod === 'office' && S.route.tab === 'gendocs' && S.route.id && id === 'dt-sign') dtSaveSoon(S.route.id);
});
document.addEventListener('input', e => {
  if (!['dt-body', 'dt-title'].includes(e.target.id) || S.route.mod !== 'office' || S.route.tab !== 'gendocs' || !S.route.id || e.target.closest('.modal')) return;
  if (e.target.id === 'dt-body') dtPvSoon(S.route.id);
  dtSaveSoon(S.route.id);
});

// ---- 2.154.0 C (#2192): data protection sheets of a client (office/privacy.py): the dialog of the client card's button
// "Data protection sheet" (which sheet, which text), the sheet's menu (PDF, mail, signed upload, check, status, archive)
// and the mail dialog (recipient, subject and text to look at and change). The section itself: clientpage.js dsb_clHtml.
const DSB_API = '/api/office/privacy-sheets';
async function dsb_new(cid) {
  let d; try { d = await api('GET', `${DSB_API}?client_id=${cid}`); } catch (x) { toast(x.message || ''); return; }
  const kinds = d.kinds || [], hint = k => kinds.find(x => x.key === k)?.hint || '';
  const md = modal(`<h3>${tr('Data protection sheet')}</h3>
    ${ofcRowF('dsb-kind', tr('Sheet'), ofcSel('dsb-kind', 'dpa', kinds.map(k => [k.key, k.label])))}
    <p class="muted ofchint" id="dsb-hint">${esc(hint('dpa'))}</p>
    ${ofcRowF('dsb-tpl', tr('Text'), ofcSel('dsb-tpl', '', (d.templates || []).map(t => [t.id, t.name]), tr('Sample')))}
    <p class="muted ofchint">${esc(tr('A text with [placeholders] opens in the editor first; the PDF is filed with the client when it is finished.'))} ${esc(d.note || '')}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Create')}</button></div>`);
  md.classList.add('ofcdlg', 'dsbdlg');
  const close = fgModal(md);
  md.addEventListener('change', e => { if (e.target.id === 'dsb-kind') { const el = $('#dsb-hint', md); if (el) el.textContent = hint(e.target.value); } });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    b.disabled = true;
    try {
      const j = await api('POST', DSB_API, {client_id: cid, kind: $('#dsb-kind', md).value, template_id: +$('#dsb-tpl', md).value || null});
      md.remove(); dsb_clReload();
      const undo = async () => { await api('DELETE', `${DSB_API}/${j.sheet.id}`); dsb_clReload(); };
      if (j.edit) { DT.data = null; DT.pv = null; go(`office/gendocs/${j.sheet.gen_doc_id}`); toast(tr('Fill in the [placeholders], then finish the document'), undo); }
      else toast(tr('Created'), undo);
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function dsb_set(x, body) {
  try { await api('PATCH', `${DSB_API}/${x.id}`, body); dsb_clReload(); } catch (e) { toast(e.message || ''); }
}
function dsb_open(x, signed) {
  const u = `${DSB_API}/${x.id}/pdf${signed ? '?signed=1' : ''}`;
  if (!signed && typeof pdfView === 'function') pdfView({url: u, name: (x.title || 'sheet') + '.pdf', dlUrl: u});
  else window.open(u, '_blank', 'noopener');  // the signed sheet may be a photo (upload / mail): the browser shows either
}
function dsb_menu(b, x) {
  if (!x) return;
  const draft = x.gen_status === 'draft', done = ['signed', 'handed'].includes(x.status);
  const st = (k, l) => x.status !== k ? {label: l, icon: 'edit', fn: () => dsb_set(x, {status: k})} : null;
  menu(b, [draft ? {label: tr('Edit and finish'), icon: 'edit', fn: () => { DT.data = null; DT.pv = null; go(`office/gendocs/${x.gen_doc_id}`); }} : null,
    !draft && x.node_id ? {label: tr('Open PDF'), icon: 'file', fn: () => dsb_open(x, false)} : null,
    x.signed_node_id ? {label: tr('Open the signed sheet'), icon: 'file', fn: () => dsb_open(x, true)} : null,
    x.review ? {label: tr('Checked: signature is fine'), icon: 'check', fn: async () => { try { await api('POST', `${DSB_API}/${x.id}/confirm`); dsb_clReload(); } catch (e) { toast(e.message || ''); } }} : null,
    !draft && !(x.sign && x.status === 'signed') ? {label: tr('Send by e-mail…'), icon: 'mail', fn: () => dsb_mail(x)} : null,
    !draft && x.sign && x.status !== 'signed' ? {label: tr('Upload the signed sheet…'), icon: 'upload', fn: () => dsb_upload(x)} : null,
    ...(draft ? [] : x.sign ? [st('signed', tr('Mark as signed')), st('declined', tr('Mark as declined')), x.review ? st('sent', tr('Not the signed sheet: back to sent')) : null]
      : [st('handed', tr('Mark as handed over'))]),
    done || x.status === 'declined' ? st('open', tr('Mark as open')) : null,
    {label: tr('Archive'), icon: 'archive', fn: async () => {
      try { await api('DELETE', `${DSB_API}/${x.id}`); dsb_clReload(); toast(tr('Archived'), async () => { await api('POST', `${DSB_API}/${x.id}/restore`); dsb_clReload(); }); } catch (e) { toast(e.message || ''); }
    }}].filter(Boolean));
}
function dsb_upload(x) {
  const i = document.createElement('input'); i.type = 'file'; i.accept = 'application/pdf,.pdf,image/jpeg,image/png';
  i.onchange = async () => {
    const f = i.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f, f.name || 'signed.pdf');
    try { await api('POST', `${DSB_API}/${x.id}/signed`, fd); toast(tr('Signed sheet filed with the client')); dsb_clReload(); } catch (e) { toast(e.message || ''); }
  };
  i.click();
}
async function dsb_mail(x) {
  let m; try { m = await api('GET', `${DSB_API}/${x.id}/mail`); } catch (e) { toast(e.message || ''); return; }
  if (!m.smtp) { toast(tr('Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)')); return; }
  const md = modal(`<h3>${tr('Send by e-mail')} · ${esc(x.kind_label)}</h3>
    ${ofcRowF('dsb-to', tr('To'), `<input id="dsb-to" type="email" value="${esc(m.to || '')}" maxlength="200" autocomplete="off">`)}
    ${ofcRowF('dsb-subj', tr('Subject'), ofcIn('dsb-subj', m.subject, {max: 200}))}
    <label for="dsb-text" class="dtp-lab">${tr('Text')}</label><textarea id="dsb-text" class="dtp-ta" rows="9" maxlength="5000">${esc(m.text || '')}</textarea>
    <p class="muted ofchint">${esc([tr('The PDF goes along as attachment.'), m.link ? tr('[Link] becomes the link to sign online.') : '', m.reply_in ? tr('A reply with the signed PDF is filed with the client; keep the code in the subject.') : ''].filter(Boolean).join(' '))}</p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="send">${ic('mail', 's')} ${tr('Send|mail')}</button></div>`);
  md.classList.add('ofcdlg', 'dsbdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    b.disabled = true;
    try {
      await api('POST', `${DSB_API}/${x.id}/send`, {to: $('#dsb-to', md).value.trim(), subject: $('#dsb-subj', md).value, text: $('#dsb-text', md).value});
      md.remove(); toast(tr('Sent')); dsb_clReload();
    } catch (er) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = er.message || ''; }
  });
}
