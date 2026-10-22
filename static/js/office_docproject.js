// @ts-check
/* Kalmido web client, Office & finance: a quotation / invoice / credit note bound to a project (2.168.0 A, #2665).
   The editor's row "Project" (pick one, none, or a new one named "Client – project title") saves over its own route, also
   on a finalised or sent document (only an internal mark; it sits outside the editor's locked fieldset). The project page's
   section "Quotations & invoices" lists its documents for people with office rights (the server answers office: false
   for everybody else). Classic script sharing the global scope with the others (module office, lazyload.js). */
'use strict';

const DPJ_KINDS = ['offer', 'invoice', 'credit'];
const DPJ = {newFor: 0, by: /** @type {Record<number, any>} */ ({}), busy: /** @type {Record<number, boolean>} */ ({})};
if (typeof OFD_ACTIONS === 'object') Object.assign(OFD_ACTIONS, {project: N_('project changed')});  // the office log's word

// the projects to pick from: lists the person sees in the office's area, not archived, no inbox / health / budget / locked
const dpj_lists = () => (S.lists || []).filter(l => !l.is_inbox && !l.archived && !l.e2e && l.life !== 'health' && l.life !== 'budget' && (l.org_id || null) === pb_clOrg() && (l.org_id || l.owner_id === S.me?.id));  // a personal office: own private projects only
function dpj_defName(d) {
  const cl = d.client_id && typeof clientById === 'function' ? clientById(d.client_id) : null;
  return [(cl?.name || d.recipient?.name || '').trim(), (d.project_title || '').trim()].filter(Boolean).join(' – ');
}
function dpj_rowHtml(d) {
  if (!d?.id || !DPJ_KINDS.includes(d.kind)) return '';
  const ls = dpj_lists(), opt = l => `<option value="${l.id}" ${l.id === d.list_id ? 'selected' : ''}>${esc(l.name)}</option>`;
  const mine = d.client_id ? ls.filter(l => l.client_id === d.client_id) : [], rest = ls.filter(l => !mine.includes(l));
  const known = !d.list_id || ls.some(l => l.id === d.list_id);
  const hidden = known ? '' : `<option value="${d.list_id}" selected>${esc(d.list_name || tr('Project (not visible)'))}</option>`;
  const groups = mine.length ? `<optgroup label="${esc(tr('Projects of the client'))}">${mine.map(opt).join('')}</optgroup><optgroup label="${esc(tr('Other projects'))}">${rest.map(opt).join('')}</optgroup>` : rest.map(opt).join('');
  const open = d.list_id && (known || d.list_name) ? `<a class="btn sm" href="#l/${d.list_id}">${ic('arrow', 's')}<span>${tr('Open project')}</span></a>` : '';
  const nw = DPJ.newFor === d.id;
  return `<div class="ofdgrid dpjrow"><div class="row"><label for="dpj-sel">${tr('Project')}</label><span class="lacts">
    <select id="dpj-sel" data-dpj="sel"><option value="">${tr('No project')}</option>${hidden}${groups}</select>${open}</span></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="dpj-new" data-dpj="new" ${nw ? 'checked' : ''}> ${tr('Create new project')}</label></div>
    ${nw ? `<div class="row dpjnew"><label for="dpj-name">${tr('Name')}</label><span class="lacts"><input id="dpj-name" maxlength="200" value="${esc(dpj_defName(d))}" placeholder="${esc(tr('Client – project title'))}">
    <button type="button" class="btn sm pri" data-dpj="make">${tr('Create')}</button></span></div>` : ''}</div>`;
}
async function dpj_set(body) {
  const d = OFD.doc; if (!d) return null;
  return await ofdSave('POST', `/api/office/docs/${d.id}/project`, body);
}
document.addEventListener('change', async e => {
  const t = /** @type {HTMLInputElement} */ (e.target);
  if (t.dataset?.dpj === 'new') { DPJ.newFor = t.checked ? OFD.doc?.id || 0 : 0; ofdDraw(); if (t.checked) setTimeout(() => /** @type {HTMLInputElement|null} */ ($('#dpj-name'))?.select(), 0); return; }
  if (t.dataset?.dpj !== 'sel' || !OFD.doc) return;
  const before = OFD.doc.list_id || null, v = t.value ? +t.value : null;
  if (v === before) return;
  if (await dpj_set({list_id: v})) toast(tr('Saved'), async () => { await dpj_set({list_id: before}); });
});
document.addEventListener('click', async e => {
  const b = /** @type {HTMLButtonElement} */ (/** @type {HTMLElement} */ (e.target).closest?.('[data-dpj="make"]'));
  if (!b || !OFD.doc) return;
  const name = (/** @type {HTMLInputElement|null} */ ($('#dpj-name'))?.value || '').trim();
  if (!name) { toast(tr('Please enter a name')); return; }
  const before = OFD.doc.list_id || null;
  b.disabled = true;
  DPJ.newFor = 0;
  const j = await dpj_set({create: {name}});
  b.disabled = false;
  if (!j) return;
  if (typeof load === 'function') await load();  // the new project in S.lists (like the pipeline)
  ofdDraw();
  if (typeof modulesOnToast === 'function') modulesOnToast(j.modules_on);
  toast(tr('Project created'), async () => { await api('PATCH', `/api/lists/${j.list_id}`, {archived: true}); await dpj_set({list_id: before}); if (typeof load === 'function') await load(); });
});

// ---- the project page: its quotations, invoices and credit notes (projects.js viewProjOv)
const DPJ_KIND = {offer: N_('Quotation'), invoice: N_('Invoice'), credit: N_('Credit note')};
function dpj_projHtml(l) {
  if (!l || l.e2e || !officeOn()) return '';
  const x = DPJ.by[l.id];
  if ((!x || x.v !== S.v) && !DPJ.busy[l.id]) {
    DPJ.busy[l.id] = true;
    api('GET', `/api/lists/${l.id}/office-docs`).then(j => { DPJ.by[l.id] = {...j, v: S.v}; }, () => { DPJ.by[l.id] = {office: false, docs: [], v: S.v}; })
      .finally(() => { DPJ.busy[l.id] = false; if (routeList()?.id === l.id) renderView(); });
  }
  if (!x?.office || !x.docs?.length) return '';
  const row = r => `<li><a class="dpjdoc" href="#office/offers/${r.id}"><span class="dpjk">${ic(r.kind === 'offer' ? 'file' : 'receipt', 's')}<span>${esc(tr(DPJ_KIND[r.kind] || r.kind))}</span></span>
    <b class="dpjn">${esc(r.number || tr('Draft'))}</b><span class="muted dpjs">${esc(r.status_text || '')}</span><span class="dpja">${esc(r.gross_text || '')}</span></a></li>`;
  return `<section class="povs dpjpov" id="pov-officedocs"><div class="povh"><h3>${tr('Quotations & invoices')}</h3><span class="spacer"></span><span class="muted">${x.docs.length}</span></div><ul class="dpjlist" role="list">${x.docs.map(row).join('')}</ul></section>`;
}
