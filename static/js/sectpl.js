// @ts-check
/* Kalmido web client: section templates (2.156.0 C, #2073), module "sectpl" (lazyload.js, loaded when the dialog opens).
   The list menu's "Section templates…" (dialogs.js listMenuItems): save the list's sections (names in their order) as a
   template - private or for an organisation (all its members see it, its creator and the admins change it) - and add a
   template's sections to this list: only the names it lacks are added at the end, nothing is removed or renamed
   (GET / POST /api/section-templates, PATCH / DELETE /api/section-templates/<id>, POST /api/lists/<id>/sections/from-template).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

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
      try { await api('DELETE', '/api/section-templates/' + id); } catch { return; }
      draw();
    }
  });
  draw();
}
