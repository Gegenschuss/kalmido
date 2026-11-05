// @ts-check
/* Kalmido web client, Office & finance: a quotation / invoice / credit note bound to a project (2.168.0 A, #2665).
   The editor's row "Project" (pick one, none, or a new one named "Client – project title") saves over its own route, also
   on a finalised or sent document (only an internal mark; it sits outside the editor's locked fieldset). The project page's
   section lists its quotations and its invoices (2.380.0 B, #3409: two groups) for people with office rights (the server answers office: false
   for everybody else). Classic script sharing the global scope with the others (module office, lazyload.js). */
'use strict';

const DPJ_KINDS = ['offer', 'invoice', 'credit'];
const DPJ = {newFor: 0, by: /** @type {Record<number, any>} */ ({}), busy: /** @type {Record<number, boolean>} */ ({})};
if (typeof OFD_ACTIONS === 'object') Object.assign(OFD_ACTIONS, {project: N_('project changed'), tasks: N_('tasks made in the project')});  // 2.537.0 C (#3433): tasks  // the office log's word

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
    <button type="button" class="btn sm pri" data-dpj="make">${tr('Create')}</button></span></div>` : ''}${d.kind === 'offer' ? otk_rowHtml(d) : ''}</div>`;
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

// ---- 2.537.0 C (#3433): tasks with a time budget from the quotation (office/offertasks.py). The button opens a preview with a
// tick per position (title page = no section, a part = a section, a shoot part = one task per crew function), the hours per row
// can be typed (piece / flat rate have none); on a quotation whose chain made tasks already it reads "Update budget from the
// quotation": new rows, changed budgets (not the ones changed by hand) and positions no longer there (only marked).
const OTK_STATE = {new: N_('New|position'), changed: N_('Changed'), manual: N_('Changed by hand'), same: N_('Unchanged'), back: N_('Back in the quotation'), gone: N_('No longer in the quotation')};
function otk_rowHtml(d) {
  const upd = (d.offer_tasks || 0) > 0;
  return `<div class="row otkrow"><span class="lacts"><button type="button" class="btn sm" data-dpj="tasks">${ic(upd ? 'sync' : 'plus', 's')}<span>${upd ? tr('Update budget from the quotation') : tr('Create tasks')}</span></button>${upd ? `<span class="muted">${esc(tr('Tasks in the project: {0}', d.offer_tasks))}</span>` : ''}</span></div>`;
}
function otk_hrs(v) { return v == null || v === '' ? '' : fmtNum(+v, 2); }
function otk_line(x) {
  const ck = x.state !== 'same', id = `otk-${x.key.replace(/[^a-z0-9]/gi, '_')}`;
  const qty = x.unit ? `${esc(x.qty_text)} ${esc(typeof ofdUnit === 'function' ? ofdUnit(x.unit, OFD.doc) : x.unit)}` : '';
  const hrs = x.state === 'gone' || x.state === 'back' ? `<span class="muted">${esc(otk_hrs(x.task_hours))}</span>`
    : `<input type="text" inputmode="decimal" class="otkh" data-otkh="${esc(x.key)}" value="${esc(otk_hrs(x.hours))}" aria-label="${esc(tr('Budget h') + ': ' + x.title)}" ${ck ? '' : 'disabled'} placeholder="–">`;
  const was = x.state === 'changed' || x.state === 'manual' ? `<small class="muted">${esc(tr('now {0} h', otk_hrs(x.task_hours) || '–'))}</small>` : '';
  return `<tr class="otk-${x.state}"><td>${ck ? `<input type="checkbox" id="${id}" data-otk="${esc(x.key)}" ${x.pick ? 'checked' : ''}>` : ''}</td>
    <td><label for="${id}"><b>${esc(x.title)}</b></label>${x.text ? `<small class="muted otktx">${esc(x.text.slice(0, 160))}</small>` : ''}</td><td class="muted">${qty}</td>
    <td>${hrs}${was}</td><td><span class="otkst">${esc(tr(OTK_STATE[x.state] || x.state))}</span></td></tr>`;
}
async function otk_open() {
  const d = OFD.doc; if (!d) return;
  let j;
  try { j = await api('GET', `/api/office/docs/${d.id}/tasks`); } catch (x) { toast(x.message || tr('unknown')); return; }
  const upd = j.linked > 0, secs = [...new Set(j.rows.map(x => x.section))];
  const rows = secs.map(s => `${s ? `<tr class="otksec"><th colspan="5">${esc(s)}</th></tr>` : ''}${j.rows.filter(x => x.section === s).map(otk_line).join('')}`).join('')
    + (j.gone.length ? `<tr class="otksec"><th colspan="5">${tr('No longer in the quotation')}</th></tr>${j.gone.map(otk_line).join('')}` : '');
  const where = j.list_id ? '' : j.list_known ? `<div class="row"><label for="otk-name">${tr('New project')}</label><input id="otk-name" maxlength="200" value="${esc(dpj_defName(d))}" placeholder="${esc(tr('Client – project title'))}"></div>`
    : `<p class="muted">${tr('You do not see the project of this quotation.')}</p>`;
  const can = j.can && j.list_known;
  const md = /** @type {any} */ (modal(`<h3>${upd ? tr('Update budget from the quotation') : tr('Create tasks')}</h3>
    <p class="muted">${esc(tr('Each position becomes a task with its budget in hours; a day counts {0} h. No prices go into the tasks.', fmtNum(j.day_hours, 2)))}</p>${where}
    <div class="scroll otkwrap"><table class="tbl otktbl"><thead><tr><th></th><th>${tr('Task')}</th><th>${tr('Quantity')}</th><th>${tr('Budget h')}</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="muted">${tr('This quotation has no positions.')}</td></tr>`}</tbody></table></div>
    <p class="otksum">${esc(tr('Budget of the project: {0} h · {1} net', fmtNum(j.total_h, 2), j.net_text))}</p>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${can ? `<button class="btn pri" data-m="ok">${upd ? tr('Apply') : tr('Create tasks')}</button>` : ''}</div>`));
  md.classList.add('otkdlg');
  md.addEventListener('click', async e => {
    const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { modalClose(md); return; }
    const pick = $$('[data-otk]', md).filter(x => /** @type {HTMLInputElement} */ (x).checked).map(x => x.dataset.otk);
    if (!pick.length) { toast(tr('Select at least one entry')); return; }
    const hours = {};
    for (const x of $$('[data-otkh]', md)) { const k = x.dataset.otkh || '', v = /** @type {HTMLInputElement} */ (x).value.trim().replace(',', '.'); if (pick.includes(k)) hours[k] = v === '' ? null : +v; }
    const req = {pick, hours};
    if (!j.list_id) { const name = (/** @type {HTMLInputElement|null} */ ($('#otk-name', md))?.value || '').trim(); if (!name) { toast(tr('Please enter a name')); return; } req.create = {name}; }
    /** @type {HTMLButtonElement} */ (b).disabled = true;
    let r;
    try { r = await api('POST', `/api/office/docs/${d.id}/tasks`, req); } catch (x) { /** @type {HTMLButtonElement} */ (b).disabled = false; toast(x.message || tr('unknown')); return; }
    modalClose(md);
    if (r.made_project && typeof load === 'function') await load();
    if (typeof modulesOnToast === 'function') modulesOnToast(r.modules_on);
    toast([r.created ? tr('Tasks created: {0}', r.created) : '', r.updated ? tr('Budgets updated: {0}', r.updated) : '', r.marked ? tr('Tasks marked: {0}', r.marked) : ''].filter(Boolean).join(' · ') || tr('Saved'));
    await ofdLoadDoc(d.id, true);
  });
}
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-dpj="tasks"]');
  if (b && OFD.doc) { e.preventDefault(); otk_open(); }
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
  const bud = x.budget ? `<p class="dpjbud">${ic('clock', 's')}<span>${esc(tr('Budget from quotation {0}: {1} h · {2} net', x.budget.number || tr('Draft'), fmtNum(x.budget.hours, 2), x.budget.net_text))}</span></p>` : '';  // 2.537.0 C (#3433)
  return `<section class="povs dpjpov" id="pov-officedocs">${bud}${grp('dpjq', N_('Quotations'), x.docs.filter(r => r.kind === 'offer'))}${grp('dpji', N_('Invoices'), x.docs.filter(r => r.kind !== 'offer'))}</section>`;
}
