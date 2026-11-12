// @ts-check
// 2.1045.0 (#5822): the section "Sees now" of the dialog "Edit agent" (agentchat.js agModal, the permissions of a personal agent in
// settings.js): what is shared with exactly this agent -- projects, knowledge folders / pages / whole areas, folders of the file
// store --, each with its role, a remove button per row and "Share…". Under the permissions a line "Nothing shared yet" for
// every permission that opens nothing without a share. It reads GET /api/agents/<id>/sees (agents/agsees.py) and shares /
// unshares only through the existing routes (fs_shares of the file store, the project's members); no share way of its own.
// The office stays the known exception (a permission without a share) and gets no line.
// html-ok below: rm / rows / more / ex are templates of this file whose own ${} are escaped (esc, Number, ic).
const AGS_HINTS = [['wiki', ['wiki:read', 'wiki:write'], N_('Knowledge pages')], ['files', ['files:read', 'files:write'], N_('File store')],
  ['project', ['tasks:write', 'sheets:read', 'sheets:write'], N_('Tasks and tables')]];
const AGS_KIND = {project: N_('Project'), wiki: N_('Knowledge|area'), files: N_('Files')};
const AGS_ROLE = {view: N_('can view'), edit: N_('can edit')};

/** @param {any} x */
function ags_rowHtml(x) {
  const where = x.kind === 'wiki' ? [x.space, x.whole ? '' : x.path] : x.kind === 'files' ? [x.path] : [];
  const sub = [tr(AGS_KIND[x.kind] || ''), ...where, x.locked ? tr('locked for the agent') : ''].filter(Boolean).join(' · ');
  const rm = x.can_remove ? `<button type="button" class="iconbtn" data-ags="rm" data-ags-kind="${esc(x.kind)}" data-ags-id="${Number(x.id)}" aria-label="${esc(tr('End the share of {0}', x.name))}" title="${esc(tr('End share'))}">${ic('x', 's')}</button>` : '';
  return `<div class="mrow ags-i" data-ags-row="${esc(x.kind)}:${Number(x.id)}"><span class="n"><b>${esc(x.name)}</b> <small class="muted">${esc(sub)}</small></span><small class="muted ags-role">${esc(tr(AGS_ROLE[x.role] || AGS_ROLE.view))}</small>${/*html-ok*/ rm}</div>`;
}
/** @param {any} j */
function ags_html(j) {
  const rows = j.items.map(ags_rowHtml).join('');
  const more = j.hidden ? `<div class="muted mhint ags-more">${esc(trn('+ {0} more share you cannot see', '+ {0} more shares you cannot see', j.hidden))}</div>` : '';
  const exn = j.except.map(x => x.path || x.name);
  if (j.except_hidden) exn.push(trn('{0} folder you cannot see', '{0} folders you cannot see', j.except_hidden));
  const ex = exn.length ? `<div class="shint keep ags-ex">${esc(tr('Excluded: {0}', exn.join(', ')))}</div>` : '';
  return `<h4 id="ags-h">${esc(tr('Sees now'))}</h4>
    <div class="ags-l" role="list" aria-labelledby="ags-h">${/*html-ok*/ rows || (j.hidden ? '' : `<div class="muted mhint ags-none">${esc(tr('Nothing shared yet: the agent sees no project, knowledge page or folder.'))}</div>`)}${/*html-ok*/ more}</div>${/*html-ok*/ ex}
    <div class="row"><label></label><button type="button" class="btn sm" data-ags="share">${ic('share', 's')} ${esc(tr('Share…'))}</button></div>`;
}
/** @param {any} j @param {any} md */
function ags_hintHtml(j, md) {
  const on = new Set([...md.querySelectorAll('.scopes [data-scope]:checked')].map(x => /** @type {any} */ (x).dataset.scope));
  return AGS_HINTS.filter(([k, sc]) => /** @type {string[]} */ (sc).some(s => on.has(s)) && !j.counts[/** @type {string} */ (k)]).map(([k, , n]) =>
    `<div class="shint keep warn ags-hint" data-ags-hint="${esc(k)}">${esc(tr('{0}: nothing shared yet, so this permission opens nothing.', tr(/** @type {string} */ (n))))} <button type="button" class="btn sm" data-ags="share" data-ags-kind="${esc(k)}">${esc(tr('Share…'))}</button></div>`).join('');
}
/** @param {any} md @param {any} a */
function ags_mount(md, a) {
  const box = md.querySelector('#ag-sees'), hint = md.querySelector('#ag-seeshint'); if (!box) return;
  const url = `/api/agents/${a.id}/sees`;
  /** @type {any} */ let j = null;
  const draw = () => { box.innerHTML = ags_html(j); if (hint) hint.innerHTML = ags_hintHtml(j, md); };
  const load = () => api('GET', url).then(r => { j = r; if (box.isConnected) draw(); }).catch(() => { box.innerHTML = ''; if (hint) hint.innerHTML = ''; });  // 404 / offline: no section
  md.addEventListener('change', e => { if (j && hint && /** @type {any} */ (e.target).closest?.('.scopes')) hint.innerHTML = ags_hintHtml(j, md); });
  md.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target).closest('[data-ags]'); if (!t || !j) return;
    if (t.dataset.ags === 'share') { ags_pick(a, t.dataset.agsKind || '', load); return; }
    const x = j.items.find(i => i.kind === t.dataset.agsKind && i.id === +t.dataset.agsId); if (!x) return;
    if (!await askConfirm(tr('End the share of {0}?', x.name), x.kind === 'project' ? tr('{0} leaves the project; its tasks there lose it as assignee.', a.name) : tr('{0} no longer sees it, at once.', a.name), {ok: tr('End share'), danger: true})) return;
    t.disabled = true;
    try {
      await api('DELETE', x.kind === 'project' ? `/api/lists/${x.list_id}/members/${a.id}` : `/api/files/shares/${x.id}`);
      toast(tr('Share ended'));
    } catch { /* shown */ }
    load();
  });
  load();
}
// "Share…": project / knowledge folder (first choice: the entire knowledge area) / folder in Files, role view / edit
/** @param {any} a @param {string} kind @param {() => any} done */
async function ags_pick(a, kind, done) {
  /** @type {any} */ let j;
  try { j = await api('GET', `/api/agents/${a.id}/sees?options=1`); } catch { return; }
  const o = j.options;
  const kinds = [['wiki', N_('Knowledge folder')], ['files', N_('Folder in Files')], ['project', N_('Project')]];
  const none = `<option value="" disabled selected>${esc(tr('Nothing you could share here'))}</option>`;
  const opts = k => {
    if (k === 'project') return o.projects.length ? o.projects.map(p => `<option value="l:${Number(p.id)}">${esc(p.name)}</option>`).join('') : none;
    if (k === 'files') return o.files.length ? o.files.map(f => `<option value="n:${Number(f.id)}">${esc(f.path)}</option>`).join('') : none;
    return o.wiki.map(s => `<optgroup label="${esc(s.space)}">${s.disabled ? `<option value="" disabled>${esc(tr('Entire knowledge area') + ' - ' + s.disabled)}</option>`
      : `<option value="n:${Number(s.root)}">${esc(tr('Entire knowledge area'))}</option>${s.folders.map(f => `<option value="n:${Number(f.id)}">${esc(f.path)}</option>`).join('')}`}</optgroup>`).join('');
  };
  const why = o.wiki.filter(s => s.disabled).map(s => `${s.space}: ${s.disabled}`);
  const md = modal(`<h3>${esc(tr('Share with {0}', a.name))}</h3>
    <div class="row"><label for="ags-k">${esc(tr('What'))}</label><select id="ags-k">${kinds.map(([k, n]) => `<option value="${esc(k)}" ${k === (kind || 'wiki') ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select></div>
    <div class="row"><label for="ags-t">${esc(tr('Where'))}</label><select id="ags-t"></select></div>
    <div class="shint keep ags-why" id="ags-why" hidden>${esc(why.join('\n'))}</div>
    <div class="row"><label for="ags-r">${esc(tr('Role'))}</label><select id="ags-r"><option value="view">${esc(tr('View'))}</option><option value="edit">${esc(tr('Edit'))}</option></select></div>
    <div class="shint keep">${esc(tr('Uses the normal sharing: you can end it here or in the sharing dialog of the folder or project.'))}</div>
    <div class="foot stfoot"><div class="calerr" role="alert" id="ags-err" hidden></div><span class="spacer"></span><button class="btn" data-agsm="close">${esc(tr('Cancel'))}</button><button class="btn pri" data-agsm="ok">${esc(tr('Share'))}</button></div>`);
  md.classList.add('agsdlg');
  const sel = /** @type {any} */ (md.querySelector('#ags-t')), ks = /** @type {any} */ (md.querySelector('#ags-k')), whyEl = /** @type {any} */ (md.querySelector('#ags-why'));
  const fill = () => { sel.innerHTML = opts(ks.value); whyEl.hidden = ks.value !== 'wiki' || !why.length; whyEl.style.whiteSpace = 'pre-line'; };
  fill();
  ks.addEventListener('change', fill);
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button[data-agsm]'); if (!b) return;
    if (b.dataset.agsm === 'close') { md.remove(); return; }
    const err = /** @type {any} */ (md.querySelector('#ags-err')), show = m => { err.textContent = m || ''; err.hidden = !m; };
    const v = String(sel.value || ''), role = /** @type {any} */ (md.querySelector('#ags-r')).value;
    if (!v) { show(tr('Select what to share')); return; }
    b.disabled = true; show('');
    try {
      const id = +v.slice(2);
      if (v.startsWith('l:')) await calReq('PUT', `/api/lists/${id}/members`, {user_id: a.id, role});
      else await calReq('POST', `/api/files/nodes/${id}/shares`, {agent_id: a.id, role});
      md.remove(); toast(tr('Shared with {0}', a.name)); done();
    } catch (x) { show(/** @type {any} */ (x).message); } finally { b.disabled = false; }
  });
}
