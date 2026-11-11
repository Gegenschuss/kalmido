// @ts-check
/* Kalmido web client: section templates (2.156.0 C, #2073), module "sectpl" (lazyload.js, loaded when the dialog opens).
   The list menu's "Section templates…" (dialogs.js listMenuItems): save the list's sections (names in their order) as a
   template - private or for an organisation (all its members see it, its admins change it; 2.905.0 #5288: a template of the core) - and add a
   template's sections to this list: only the names it lacks are added at the end, nothing is removed or renamed
   (GET / POST /api/section-templates, PATCH / DELETE /api/section-templates/<id>, POST /api/lists/<id>/sections/from-template).
   2.609.0 (#3372): also the project dialog's "Types and templates…" (ticketTplModal, from dialogs.js, start budget #4198).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.979.0 (#5667): a template's delete the server took back by its group: the open dialog fetches its templates again
histReloader('sectpl', () => /** @type {any} */ ($('.sctmodal'))?._reload?.());
async function sct_open(lid) {
  const l = listById(lid); if (!l) return;
  const secs = S.sections.filter(s => s.list_id === lid);
  const ws = wsOn() ? `<label class="sctws"><span>${esc(tr('Workspace'))}</span>${wsSelectHtml('sct-ws', l.org_id || null)}</label>` : '';
  const md = modal(`<div class="lhdr"><h3>${ic('copy', 's')} ${esc(tr('Section templates'))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="sctsave">
      <div class="shint">${esc(secs.length ? tr('Save the {0} sections of this project as a template:', String(secs.length)) : tr('This project has no sections yet.'))}</div>
      ${secs.length ? `<div class="row sctrow"><input id="sct-name" type="text" maxlength="200" aria-label="${esc(tr('Template name'))}" placeholder="${esc(tr('Template name'))}" value="${esc(lname(l))}">${ws}<button class="btn pri" data-m="save">${esc(tr('Save'))}</button></div>` : ''}
    </div>
    <h4 class="scth">${esc(tr('Add sections from a template'))}</h4>
    <div class="shint">${esc(tr('Only the sections this project does not have yet are added; nothing is removed.'))}</div>
    <div id="sct-list" class="sctlist"><p class="muted">${esc(tr('Loading…'))}</p></div>`);
  md.classList.add('sctmodal');
  let cur = [];
  const draw = async () => {
    const box = md.querySelector('#sct-list'); if (!box) return;
    let ts;
    try { ts = (await api('GET', '/api/section-templates')).templates || []; } catch { box.innerHTML = `<p class="muted">${esc(tr('Templates are only available online.'))}</p>`; return; }
    box.innerHTML = ts.map(t => `<div class="mrow sctt" data-sct="${t.id}"><span class="n">${esc(t.name)} <span class="muted">${esc(t.sections.join(' · '))}</span>${t.org_id ? `<span class="muted sctorg">${esc(wsName('org:' + t.org_id))}</span>` : ''}</span>
      <button class="btn sm" data-m="apply" data-id="${t.id}">${esc(tr('Add'))}</button>${t.can_edit ? `<button class="iconbtn" data-m="del" data-id="${t.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete') + ': ' + t.name)}">${ic('trash', 's')}</button>` : ''}</div>`).join('')
      || `<p class="muted">${esc(tr('No section templates yet.'))}</p>`;
    cur = ts;
  };
  /** @type {any} */ (md)._reload = draw;  // 2.979.0 (#5667): histReloader above sct_open
  md.addEventListener('click', async e => {
    const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-m]'); if (!b) return;
    const m = b.getAttribute('data-m');
    if (m === 'close') { md.remove(); return; }
    if (m === 'save') {
      const name = (/** @type {HTMLInputElement} */ (md.querySelector('#sct-name'))?.value || '').trim();
      if (!name) { toast(tr('Name missing')); return; }
      const w = /** @type {HTMLSelectElement} */ (md.querySelector('#sct-ws'))?.value || '';
      try { await api('POST', '/api/section-templates', {name, list_id: lid, space: w ? 'org:' + w : 'private'}); } catch { return; }  // api() showed it
      toast(tr('Saved')); draw();
      return;
    }
    const id = +(b.getAttribute('data-id') || 0), t = cur.find(x => x.id === id); if (!t) return;
    if (m === 'apply') {
      let r; try { r = await api('POST', `/api/lists/${lid}/sections/from-template`, {template_id: id}); } catch { return; }
      const n = (r?.added || []).length;
      await load(); render();
      toast(n ? trn('{0} section added', '{0} sections added', n) : tr('This project has all of them already'));
      if (n) md.remove();
      return;
    }
    if (m === 'del') {
      if (!await askConfirm(tr('Delete the template “{0}”?', t.name), tr('Projects made with it keep their sections.'), {ok: tr('Delete'), danger: true})) return;
      let j; try { j = await api('DELETE', '/api/section-templates/' + id); } catch { return; }
      draw();
      // 2.905.0 (#5288): it waits in the trash of templates (a template of the core): the toast and the undo history take it back out
      offerUndo(tr('Template deleted'), histAdd({label: tr('Template “{0}” deleted', t.name), ...(j?.undo_group ? {srv: true} : {}), undo: async () => { await api('POST', `/api/templates/${id}/restore`); draw(); }, redo: async () => { await api('DELETE', '/api/section-templates/' + id); draw(); }}));
    }
  });
  draw();
}

// 2.4.0 (#340): the note templates of new bug / feature tickets of a list (empty = the built-in text)
// 2.609.0 (#3372): + which types the project offers (none ticked = all of its workspace), templates of the own types
function ticketTplModal(lid) {
  const l = listById(lid); if (!l) return;
  let cur = {}; try { cur = JSON.parse(l.ticket_tpl || '{}') || {}; } catch { /* bad json */ }
  let pick = []; try { pick = JSON.parse(l.ttypes || '[]') || []; } catch { /* bad json */ }
  const def = {bug: tr('**Steps to reproduce**\n1. \n\n**Expected**\n\n**Actual**\n\n**Environment**\n\n**Version / found in**\n'), feature: tr('**Goal**\n\n**Acceptance criteria**\n- [ ] \n')};
  const own = tty_ofList(lid).filter(r => r.enabled), all = [...TTYPES.map(x => x[0]), ...own.map(r => r.key)];
  for (const r of own) def[r.key] = r.template || '';
  const tplKeys = ['bug', 'feature', ...own.map(r => r.key)];
  /** @type {any} */
  const md = modal(`<h3>${tr('Ticket types and templates')}</h3>
    <div class="row"><label>${tr('Offered types')}</label><span class="ttpick">${all.map(k => ttInfo(k, lid)).map(x => `<label class="chkl"><input type="checkbox" data-ttk="${esc(x.key)}" ${pick.includes(x.key) ? 'checked' : ''}> ${ic(x.icon, 's')} ${esc(x.name)}</label>`).join('')}</span></div>
    <div class="shint">${tr('None ticked = all types of the workspace (own types: Settings > Data > Ticket types).')}</div>
    <div class="row"><label for="tt-def">${tr('Type of new tasks')}</label><select id="tt-def"><option value="">${tr('No type')}</option>${[...new Set([...all, ...(l.def_ttype ? [l.def_ttype] : [])])].map(k => ttInfo(k, lid)).map(x => `<option value="${esc(x.key)}" ${l.def_ttype === x.key ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
    <div class="shint">${tr('New tickets of this type start with these notes (Markdown) when their notes are empty. Empty = the built-in text.')}</div>
    ${tplKeys.map(k => ttInfo(k, lid)).map(x => `<div class="row ppcol"><label for="tt-${esc(x.key)}">${ic(x.icon, 's')} ${esc(x.name)}</label><textarea id="tt-${esc(x.key)}" data-tpl="${esc(x.key)}" rows="6" maxlength="5000" placeholder="${esc(def[x.key] || '')}">${esc(cur[x.key] || '')}</textarea></div>`).join('')}
    <div class="foot"><button class="btn" data-m="reset">${tr('Built-in texts')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ttmodal');
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'reset') { $$('[data-tpl]', md).forEach(x => { x.value = ''; }); return; }
    if (b.dataset.m === 'save') {
      // 2.46.2 (#1659): at once (optimistic), no reload of the whole state; an error puts the old templates back
      const tpl = Object.fromEntries($$('[data-tpl]', md).map(x => [x.dataset.tpl, x.value])), dt = $('#tt-def', md).value;  // 2.483.0 (#3916): + the default type
      const tk = $$('[data-ttk]:checked', md).map(x => x.dataset.ttk);  // 2.609.0 (#3372)
      // the dialog closes once the server has it: on an error the typed texts are still there
      optWrite(optSet(() => listById(lid), {ticket_tpl: JSON.stringify(tpl), def_ttype: dt, ttypes: tk.length ? JSON.stringify(tk) : ''}), () => api('PATCH', '/api/lists/' + lid, {ticket_tpl: tpl, def_ttype: dt, ttypes: tk}))
        .then(() => { md.remove(); toast(tr('Saved')); }).catch(() => {});
    }
  });
}
