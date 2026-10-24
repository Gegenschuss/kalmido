/* Kalmido web client: tables, step 2 (2.89.0, #1916 part D) -- carrying data over BY BUTTON, never a silent live link:
   rows -> tasks of a list, the sheet (or chosen rows) -> a quotation draft in the office, a list / project -> rows with live
   task values (aufgabe.<id>.<field>) and "fetch the list's new tasks". Each press is one undo step (server: sheets/step2.py,
   POST /api/sheets/<id>/links/<batch>/undo | redo). Hangs into sheets.js through SHV_HOOKS (menu, row, side).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

window.SHV_HOOKS = window.SHV_HOOKS || {};
for (const k of ['menu', 'overview', 'row', 'side']) window.SHV_HOOKS[k] = window.SHV_HOOKS[k] || [];
const SH2 = {d: {}, busy: {}};  // sheet id -> {rev, links, lists, office, clients} of GET /api/sheets/<id>/links

function sh2Data(sh) {  // the marks + dialog data of the open sheet (loads them once per change of the sheet)
  const d = SH2.d[sh.id];
  if ((!d || d.rev !== sh.rev) && !SH2.busy[sh.id]) sh2Load(sh);
  return d || null;
}
async function sh2Load(sh) {
  const sid = sh.id, rev = sh.rev; SH2.busy[sid] = 1;
  try { SH2.d[sid] = {...await rawFetch('GET', `/api/sheets/${sid}/links`), rev}; }
  catch (e) { SH2.d[sid] = {links: [], lists: [], office: false, clients: [], rev, err: e.message}; }
  finally { delete SH2.busy[sid]; }
  if (SHV.sh?.id === sid && typeof shvRender === 'function') shvRender();
}
const sh2Drop = sid => { delete SH2.d[sid]; };
async function sh2Fresh(sh) { sh2Drop(sh.id); await sh2Load(sh); return SH2.d[sh.id]; }

// ---- the chosen rows (a range over several rows), else every row
function sh2Chosen() {
  const r = typeof shvRect === 'function' ? shvRect() : null;
  if (!r || r.r0 === r.r1) return null;
  return shvGrid()[0].slice(r.r0, r.r1 + 1);
}
const sh2ColName = c => (c.letter || '') + (c.title ? ' · ' + c.title : '');
const sh2ColOpts = (sh, sel, none) => (none ? `<option value="">${esc(tr('None'))}</option>` : '')
  + sh.columns.map(c => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(sh2ColName(c))}</option>`).join('');
const sh2Find = (sh, kinds, rx) => (sh.columns.find(c => rx && rx.test(c.title || '')) || sh.columns.find(c => kinds.includes(c.kind)) || {}).id || null;
const sh2Field = (id, label, inner) => `<label class="sh2f" for="${id}"><span>${esc(label)}</span><select id="${id}">${inner}</select></label>`;
function sh2RowsChoice(sh, chosen) {  // "only the chosen rows (n)" / "all rows"
  return chosen ? `<fieldset class="sh2rows"><legend class="sr">${esc(tr('Rows'))}</legend>
    <label><input type="radio" name="sh2-rows" value="sel" checked> ${esc(trn('Only the chosen row', 'Only the {0} chosen rows', chosen.length))}</label>
    <label><input type="radio" name="sh2-rows" value="all"> ${esc(tr('All rows'))}</label></fieldset>` : `<p class="muted mhint">${esc(tr('All rows with content are carried over. Choose several rows first to take only those.'))}</p>`;
}
const sh2Val = (md, id) => { const v = $('#' + id, md)?.value; return v ? +v : null; };
const sh2RowsOf = (md, chosen) => chosen && $('input[name="sh2-rows"]:checked', md)?.value !== 'all' ? chosen : null;
async function sh2Ask(title, html, ok, read) {  // askDialog with fields: read(md) collects them before the dialog closes
  let vals = null;
  const yes = await askDialog({title, html, ok, after: md => md.querySelector('form').addEventListener('submit', () => { vals = read(md); }, true)});
  return yes ? vals : null;
}

// ---- rows -> tasks
async function sh2ToTasks(sh) {
  const d = SH2.d[sh.id] || await sh2Fresh(sh), chosen = sh2Chosen();
  const lists = (d?.lists || []).filter(l => l.writable);
  if (!lists.length) { toast(tr('There is no project in this space you may add tasks to.')); return; }
  const pre = sh.list_id && lists.some(l => l.id === sh.list_id) ? sh.list_id : lists[0].id;
  const html = `${sh2Field('sh2-list', tr('Project'), lists.map(l => `<option value="${l.id}" ${l.id === pre ? 'selected' : ''}>${esc(l.name)}</option>`).join(''))}
    ${sh2Field('sh2-title', tr('Title'), sh2ColOpts(sh, sh2Find(sh, ['text'])))}
    ${sh2Field('sh2-due', tr('Due'), sh2ColOpts(sh, sh2Find(sh, ['date']), true))}
    ${sh2Field('sh2-notes', tr('Notes'), sh2ColOpts(sh, null, true))}${sh2RowsChoice(sh, chosen)}
    <p class="muted mhint">${esc(tr('Rows carried over before and rows without a title are skipped. Not linked afterwards.'))}</p>`;
  const v = await sh2Ask(tr('Create tasks from rows'), html, tr('Create tasks'), md => ({list_id: sh2Val(md, 'sh2-list'), title_col: sh2Val(md, 'sh2-title'),
    due_col: sh2Val(md, 'sh2-due'), notes_col: sh2Val(md, 'sh2-notes'), rows: sh2RowsOf(md, chosen)}));
  if (!v) return;
  const lname0 = lists.find(l => l.id === v.list_id)?.name || '';
  await sh2Step(sh, tr('Tasks from {0}', qn(sh.title || tr('Untitled table'))), 'to-tasks', v,
    r => trn('{0} task created in {1}', '{0} tasks created in {1}', r.tasks.length, qn(lname0)) + (r.skipped ? ' · ' + trn('{0} row skipped', '{0} rows skipped', r.skipped) : ''));
}
async function sh2Step(sh, label, path, body, msg, redo = true) {  // one press = one undo step (undo / redo by its batch)
  const sid = sh.id, at = `/api/sheets/${sid}/links/`;
  let res = await shvStep(label, async () => { const r = await rawFetch('POST', `/api/sheets/${sid}/${path}`, body); sh2Drop(sid); return r; },
    async r => { if (!r.batch) return; const u = await rawFetch('POST', at + r.batch + '/undo'); sh2Drop(sid); if (u.kept?.length) toast(tr('The quotation draft stays in the office: only its admin can delete it.')); },
    null, redo ? async r => { if (r.batch) await rawFetch('POST', at + r.batch + '/redo'); sh2Drop(sid); } : null);
  if (res) { const m = msg(res); if (m) { const e = HIST.undo[HIST.undo.length - 1]; e ? histToast(m, e) : toast(m); } }
  return res;
}

// ---- sheet -> quotation draft
async function sh2ToOffer(sh) {
  const d = SH2.d[sh.id] || await sh2Fresh(sh), chosen = sh2Chosen();
  if (!d?.office) { toast(tr('Office & finance is not available for this table\'s space')); return; }
  const html = `${sh2Field('sh2-desc', tr('Description'), sh2ColOpts(sh, sh2Find(sh, ['text'], /beschreib|leistung|position|descr|item|titel|title/i)))}
    ${sh2Field('sh2-qty', tr('Quantity'), sh2ColOpts(sh, sh2Find(sh, ['number'], /menge|anzahl|stunden|tage|qty|quant|hours|days/i), true))}
    ${sh2Field('sh2-unit', tr('Unit'), sh2ColOpts(sh, sh2Find(sh, [], /einheit|unit/i), true))}
    ${sh2Field('sh2-price', tr('Unit price'), sh2ColOpts(sh, sh2Find(sh, ['currency'], /preis|satz|price|rate/i), true))}
    ${sh2Field('sh2-client', tr('Client'), `<option value="">${esc(tr('No client'))}</option>` + (d.clients || []).map(c => `<option value="${c.id}">${esc(cdn_label(c))}</option>`).join(''))}
    ${sh2RowsChoice(sh, chosen)}<p class="muted mhint">${esc(tr('A draft is created in the office; check and send it there. Nothing is finalised.'))}</p>`;
  const v = await sh2Ask(tr('Take over as a quotation'), html, tr('Create draft'), md => ({desc_col: sh2Val(md, 'sh2-desc'), qty_col: sh2Val(md, 'sh2-qty'),
    unit_col: sh2Val(md, 'sh2-unit'), price_col: sh2Val(md, 'sh2-price'), client_id: sh2Val(md, 'sh2-client'), rows: sh2RowsOf(md, chosen)}));
  if (!v) return;
  await sh2Step(sh, tr('Quotation from {0}', qn(sh.title || tr('Untitled table'))), 'to-offer', v,
    r => tr('Quotation draft {0} created', r.number || ''), false);
  sh2Drop(sh.id);
}

// ---- list -> rows (live task values)
async function sh2FromList(sh, lid) {
  const d = SH2.d[sh.id] || await sh2Fresh(sh);
  if (!lid) {
    const ls = d?.lists || [];
    if (!ls.length) { toast(tr('There is no project in this space.')); return; }
    const pre = sh.list_id && ls.some(l => l.id === sh.list_id) ? sh.list_id : ls[0].id;
    const v = await sh2Ask(tr('Project as rows'), `${sh2Field('sh2-src', tr('Project'), ls.map(l => `<option value="${l.id}" ${l.id === pre ? 'selected' : ''}>${esc(l.name)}</option>`).join(''))}
      <p class="muted mhint">${esc(tr('One row per task, the values stay live. You fetch new tasks later.'))}</p>`,
      tr('Add rows'), md => ({list_id: sh2Val(md, 'sh2-src')}));
    if (!v) return;
    lid = v.list_id;
  }
  await sh2Step(sh, tr('Rows from a project'), 'rows-from-list', {list_id: lid},
    r => r.added ? trn('{0} row added', '{0} rows added', r.added) : tr('No new tasks in the project.'));
}
function sh2SrcLists(sh, d) {  // the lists this sheet already has rows of (for "fetch new tasks")
  return (d?.row_lists || []).map(id => (d.lists || []).find(l => l.id === id)).filter(Boolean);
}

// ---- hooks: the sheet's menu, the row marks, the side panel
SHV_HOOKS.menu.push(sh => {
  if (!sh?.can_write || sh.shared_in) return [];  // 2.124.0 C (#2113): carrying over never through a share
  const d = sh2Data(sh), out = ['-', {label: tr('Create tasks from rows…'), icon: 'check', fn: () => sh2ToTasks(sh)}];
  if (d?.office) out.push({label: tr('Take over as a quotation…'), icon: 'receipt', fn: () => sh2ToOffer(sh)});
  out.push({label: tr('Project as rows…'), icon: 'download', fn: () => sh2FromList(sh)});
  for (const l of sh2SrcLists(sh, d)) out.push({label: tr('Fetch new tasks of {0}', l.name), icon: 'sync', fn: () => sh2FromList(sh, l.id)});
  return out;
});
const sh2RowLinks = (sh, rid) => (sh2Data(sh)?.links || []).filter(x => x.row_id === rid && x.kind === 'task');
const sh2Label = x => x.denied ? tr('No access') : x.deleted ? tr('Deleted') : x.label || '';
SHV_HOOKS.row.push((sh, r) => {  // a small mark in the row's head: carried over into a task
  const ls = sh2RowLinks(sh, r.id); if (!ls.length) return '';
  const t = ls.map(x => tr('Carried over into {0}', sh2Label(x))).join(' · ');
  return `<span class="sh2mark" title="${esc(t)}" aria-label="${esc(t)}">${ic('check', 's')}</span>`;
});
SHV_HOOKS.side.push(sh => {  // the chosen row's carry-overs + the quotations of the sheet, with links
  const d = sh2Data(sh); if (!d?.links?.length) return '';
  const rid = SHV.cur?.r, mine = d.links.filter(x => (x.kind === 'task' && x.row_id === rid) || x.kind === 'offer');
  if (!mine.length) return '';
  const li = x => {
    const lab = sh2Label(x), ok = !x.denied && !x.deleted;
    const href = x.kind === 'task' ? `#t/${+x.target_id}` : `#office/offers/${+x.target_id}`;
    return `<li>${ic(x.kind === 'task' ? 'check' : 'receipt', 's')}${ok ? `<a href="${href}" class="shvsrc">${esc(x.kind === 'task' ? tr('Task {0}', lab) : tr('Quotation {0}', lab))}</a>` : `<span class="shverr">${esc(lab)}</span>`}
      <span class="muted">${esc(x.created_at ? relTime(x.created_at) : '')}</span></li>`;
  };
  return `<section class="shvsec"><h4>${tr('Carried over')}</h4><ul class="shvrefs">${mine.map(li).join('')}</ul></section>`;
});
