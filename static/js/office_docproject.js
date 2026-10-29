// @ts-check
/* Kalmido web client, Office & finance: a quotation / invoice / credit note bound to a project (2.168.0 A, #2665).
   The editor's row "Project" (pick one, none, or a new one named "Client – project title") saves over its own route, also
   on a finalised or sent document (only an internal mark; it sits outside the editor's locked fieldset). The project page's
   section lists its quotations and its invoices (2.380.0 B, #3409: two groups) for people with office rights (the server answers office: false
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
// 2.435.0 (#3606): the row shows a button with the project's icon and name (as the sidebar shows it); a click opens the
// project picker of "Move to project" (No project, the client's projects, then the rest in the sidebar's order, a search
// from 10 entries, a sheet on a phone) instead of a native select with the names' old emojis
function dpj_rowHtml(d) {
  if (!d?.id || !DPJ_KINDS.includes(d.kind)) return '';
  const ls = dpj_lists(), l = d.list_id ? ls.find(x => x.id === d.list_id) : null;
  const known = !d.list_id || !!l;
  const cur = l ? `${listIconHtml(l, {cls: 'mlic'}) || ic('list', 's')}<span class="dpjnm">${esc(licName(l))}</span>`
    : d.list_id ? `${ic('list', 's')}<span class="dpjnm">${esc(d.list_name || tr('Project (not visible)'))}</span>` : `<span class="dpjnm muted">${tr('No project')}</span>`;
  const open = d.list_id && (known || d.list_name) ? `<a class="btn sm" href="#l/${d.list_id}">${ic('arrow', 's')}<span>${tr('Open project')}</span></a>` : '';
  const nw = DPJ.newFor === d.id;
  return `<div class="ofdgrid dpjrow"><div class="row"><label for="dpj-sel">${tr('Project')}</label><span class="lacts">
    <button type="button" class="btn sm dpjpick" id="dpj-sel" data-dpj="sel" data-lid="${d.list_id || ''}" aria-haspopup="menu">${cur}${ic('down', 's dpjchev')}</button>${open}</span></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="dpj-new" data-dpj="new" ${nw ? 'checked' : ''}> ${tr('Create new project')}</label></div>
    ${nw ? `<div class="row dpjnew"><label for="dpj-name">${tr('Name')}</label><span class="lacts"><input id="dpj-name" maxlength="200" value="${esc(dpj_defName(d))}" placeholder="${esc(tr('Client – project title'))}">
    <button type="button" class="btn sm pri" data-dpj="make">${tr('Create')}</button></span></div>` : ''}</div>`;
}
async function dpj_set(body) {
  const d = OFD.doc; if (!d) return null;
  return await ofdSave('POST', `/api/office/docs/${d.id}/project`, body);
}
async function dpj_pickTo(v) {
  if (!OFD.doc) return;
  const before = OFD.doc.list_id || null;
  if (v === before) return;
  if (await dpj_set({list_id: v})) toast(tr('Saved'), async () => { await dpj_set({list_id: before}); });
}
function dpj_picker(b) {
  const d = OFD.doc; if (!d) return;
  const ls = dpj_lists(), mine = d.client_id ? ls.filter(l => l.client_id === d.client_id) : [];
  tch_listPicker(b, {title: tr('Project'), filter: l => ls.includes(l), on: d.list_id || 0, search: 10,
    pre: [{label: tr('No project'), icon: 'ban', on: !d.list_id, fn: () => dpj_pickTo(null)}],
    first: mine.length ? {head: tr('Projects of the client'), lists: mine, rest: tr('Other projects')} : null,
    pick: l => dpj_pickTo(l.id)});
}
document.addEventListener('change', async e => {
  const t = /** @type {HTMLInputElement} */ (e.target);
  if (t.dataset?.dpj === 'new') { DPJ.newFor = t.checked ? OFD.doc?.id || 0 : 0; ofdDraw(); if (t.checked) setTimeout(() => /** @type {HTMLInputElement|null} */ ($('#dpj-name'))?.select(), 0); }
});
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-dpj="sel"]');
  if (b && OFD.doc) { e.preventDefault(); dpj_picker(/** @type {HTMLElement} */ (b)); }
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
  const row = r => `<li><a class="dpjdoc" href="#office/${r.kind === 'offer' ? 'offers' : 'invoices'}/${r.id}"><span class="dpjk">${ic(r.kind === 'offer' ? 'file' : 'receipt', 's')}<span>${esc(tr(DPJ_KIND[r.kind] || r.kind))}</span></span>
    <b class="dpjn">${esc(r.number || tr('Draft'))}</b><span class="muted dpjs">${esc(r.status_text || '')}</span><span class="dpja">${esc(r.gross_text || '')}</span></a></li>`;
  // 2.380.0 B (#3409): quotations and invoices as two groups (the office's two areas), each with its count
  const grp = (cls, name, xs) => xs.length ? `<div class="povh ${cls}"><h3>${esc(tr(name))}</h3><span class="spacer"></span><span class="muted">${xs.length}</span></div><ul class="dpjlist" role="list">${xs.map(row).join('')}</ul>` : '';
  return `<section class="povs dpjpov" id="pov-officedocs">${grp('dpjq', N_('Quotations'), x.docs.filter(r => r.kind === 'offer'))}${grp('dpji', N_('Invoices'), x.docs.filter(r => r.kind !== 'offer'))}</section>`;
}
