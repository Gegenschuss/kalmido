// @ts-check
/* Kalmido web client: the field schema of an organisation (2.609.0 , #3373), module "orgschema" (lazyload.js, loaded when a
   project's settings show their custom fields). The fields of the project's organisation (without one: the owner's own fields)
   are switched on per project; a switched-on field is a linked custom field of the project (its name and options are the
   organisation's). The organisation's admins (or the person for their own fields) add, change and delete them in "Manage…".
   (GET / POST /api/org-fields, PATCH / DELETE /api/org-fields/<id>, GET /api/lists/<id>/org-fields, PUT /api/lists/<id>/org-fields/<id>).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const OFS_NO_TYPES = ['formula'];  // a formula names the fields of one project
const ofs_space = lid => { const l = listById(lid); return l?.org_id ? 'org:' + l.org_id : 'private'; };
const ofs_admin = lid => { const l = listById(lid); return l?.org_id ? (S.me?.workspaces || []).some(o => o.id === l.org_id && o.role === 'admin') : l?.owner_id === S.me?.id; };

async function ofs_mount(box, lid, redraw) {
  if (!box || !lid || !navigator.onLine) return;
  let j; try { j = await api('GET', `/api/lists/${lid}/org-fields`); } catch { return; }
  if (!box.isConnected) return;
  box.querySelector('.ofsbox')?.remove();
  const fs = j.fields || [], adm = ofs_admin(lid);
  if (!fs.length && !adm) return;
  const org = !!listById(lid)?.org_id;
  const el = document.createElement('div');
  el.className = 'ofsbox';
  el.innerHTML = `<div class="mrow ofshead"><b>${esc(org ? tr('Fields of the organisation') : tr('My field templates'))}</b><span class="spacer"></span>${adm ? `<button type="button" class="btn sm" data-ofs="manage">${esc(tr('Manage…'))}</button>` : ''}</div>
    ${fs.map(f => `<label class="mrow chkl ofsrow"><input type="checkbox" data-ofson="${f.id}" ${f.field_id ? 'checked' : ''}> <span class="n">${esc(f.name)}</span><span class="muted">${esc(ftLabel(f.type))} · ${esc(f.key)}</span></label>`).join('')
      || `<div class="muted mhint">${esc(org ? tr('The organisation has no fields yet.') : tr('No field templates yet: fields made here can be switched on in each of your projects.'))}</div>`}`;
  box.appendChild(el);
  el.addEventListener('change', async e => {
    const x = /** @type {HTMLInputElement} */ (e.target), ofid = x.dataset?.ofson; if (!ofid) return;
    x.disabled = true;
    try { await api('PUT', `/api/lists/${lid}/org-fields/${ofid}`, {on: x.checked}); } catch { x.checked = !x.checked; x.disabled = false; return; }
    await load(); render(); redraw && redraw();
  });
  el.addEventListener('click', e => {
    const b = /** @type {HTMLElement} */ (e.target).closest('[data-ofs="manage"]'); if (!b) return;
    ofs_manage(ofs_space(lid), () => redraw && redraw());
  });
}

async function ofs_manage(space, done) {
  const md = modal(`<div class="lhdr"><h3>${esc(space === 'private' ? tr('My field templates') : tr('Fields of the organisation'))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="shint">${esc(tr('A change reaches every project that uses the field. The key stays the same in every project (API filter fkey_ and the key).'))}</div>
    <div class="members" id="ofs-list"><p class="muted">${esc(tr('Loading…'))}</p></div>
    <div class="foot"><button class="btn sm" data-m="add">${ic('plus', 's')} ${esc(tr('Field'))}</button><span class="spacer"></span><button class="btn" data-m="close">${esc(tr('Close'))}</button></div>`);
  let cur = [];
  const ep = {post: '/api/org-fields', one: id => '/api/org-fields/' + id, noType: OFS_NO_TYPES, extra: {space}};
  const draw = async () => {
    const box = md.querySelector('#ofs-list'); if (!box) return;
    try { cur = ((await api('GET', '/api/org-fields')).fields || []).filter(f => f.space === space); } catch { box.innerHTML = `<p class="muted">${esc(tr('Only available online.'))}</p>`; return; }
    box.innerHTML = cur.map(f => `<div class="mrow">${ic(FT_ICON[f.type] || 'edit', 's')}<span class="n">${esc(f.name)}</span><span class="muted">${esc(ftLabel(f.type))} · ${esc(f.key)} · ${esc(trn('{0} project', '{0} projects', f.lists))}</span>${f.can_edit ? `<button class="iconbtn" data-ofe="${f.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit') + ': ' + f.name)}">${ic('edit', 's')}</button>` : ''}</div>`).join('')
      || `<p class="muted">${esc(tr('No fields yet.'))}</p>`;
  };
  draw();
  md.addEventListener('click', e => {
    const b = /** @type {HTMLElement} */ (e.target).closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); done && done(); return; }
    if (b.dataset.m === 'add') { fieldModal(null, null, draw, ep); return; }
    if (b.dataset.ofe) { const f = cur.find(x => x.id === +b.dataset.ofe); if (f) fieldModal(null, f, async () => { await draw(); await load(); render(); }, ep); }
  });
}

// 2.609.0 (#3373): a new task of a project with required fields (createTask, undo.js) asks for their values first; null =
// cancelled. The server checks the same (400 naming the field), so a client that does not ask learns which field is missing.
function rqf_ask(lid, body) {
  const fs = fieldsOf(lid).filter(f => f.required && body.fields?.[f.id] == null);
  if (!fs.length) return Promise.resolve({});
  const t0 = {id: 0, list_id: lid, fields: {}};
  const inp = f => f.type === 'multiselect' ? `<select id="cf-${f.id}" data-cf="${f.id}" multiple>${(f.options?.options || []).map(o => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join('')}</select>`
    : f.type === 'rating' ? `<input id="cf-${f.id}" data-cf="${f.id}" type="number" min="1" max="${f.options?.max || 5}" inputmode="numeric">`
    : f.type === 'task' ? `<input id="cf-${f.id}" data-cf="${f.id}" inputmode="numeric" placeholder="#123">` : null;
  return new Promise(done => {
    const md = modal(`<h3>${esc(tr('Required fields'))}</h3>
      <div class="shint">${esc(tr('“{0}” needs these fields:', String(body.title || '').slice(0, 60)))}</div>
      <div class="fields cf rqfgrid">${fs.map(f => { const x = inp(f); return x ? `<label for="cf-${f.id}">${esc(f.name)}</label>${x}` : fieldEditor(f, t0, false); }).join('')}</div>
      <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${esc(tr('Cancel'))}</button><button class="btn pri" data-m="ok">${esc(tr('Create'))}</button></div>`);
    md.classList.add('rqfmodal');
    let out = null;
    onRemove(md, () => done(out));
    md.addEventListener('click', e => {
      const b = /** @type {HTMLElement} */ (e.target).closest('[data-m]'); if (!b) return;
      if (b.dataset.m === 'close') { md.remove(); return; }
      if (b.dataset.m !== 'ok') return;
      const fv = {};
      for (const f of fs) {
        const el = /** @type {HTMLInputElement} */ (md.querySelector(`[data-cf="${f.id}"]`));
        const v = !el ? null : f.type === 'multiselect' ? [...(/** @type {any} */ (el)).selectedOptions].map(o => o.value) : cf_val(el, f);
        if (v == null || (Array.isArray(v) && !v.length)) { if (el) need(el); toast(tr('Required field missing: {0}', f.name)); return; }
        fv[f.id] = v;
      }
      out = fv; md.remove();
    });
    setTimeout(() => /** @type {HTMLElement} */ (md.querySelector('[data-cf]'))?.focus(), 0);
  });
}

// 2.609.0 (#3373): the labels of an organisation (admins): a project tag in every project of the organisation; personal tags
// stay private (GET / POST /api/org-labels, PATCH / DELETE /api/org-labels/<id>)
async function olb_manage(oid, done) {
  if (!oid) return;
  const md = modal(`<div class="lhdr"><h3>${esc(tr('Labels of the organisation'))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="shint">${esc(tr('Every project of the organisation offers these labels; a change reaches all of them. Personal tags stay private.'))}</div>
    <div class="members" id="olb-list"><p class="muted">${esc(tr('Loading…'))}</p></div>
    <div class="row"><input id="olb-new" placeholder="${esc(tr('New label'))}" maxlength="60" aria-label="${esc(tr('New label'))}"><button class="btn sm" data-m="add">${ic('plus', 's')} ${esc(tr('Add'))}</button></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${esc(tr('Close'))}</button></div>`);
  let cur = [];
  const draw = async () => {
    const box = md.querySelector('#olb-list'); if (!box) return;
    try { cur = (await api('GET', '/api/org-labels?org_id=' + oid)).labels || []; } catch { box.innerHTML = `<p class="muted">${esc(tr('Only available online.'))}</p>`; return; }
    box.innerHTML = cur.map(x => `<div class="mrow" data-olbid="${x.id}"><span class="ltsw" style="${cssColor(x.color) ? 'background:' + cssColor(x.color) : ''}"></span><span class="n">#${esc(x.name)} <span class="muted">${esc(trn('{0} project', '{0} projects', x.lists))}</span></span>
      <button class="iconbtn" data-m="color" title="${esc(tr('Colour'))}">${ic('palette', 's')}</button><button class="iconbtn" data-m="ren" title="${esc(tr('Rename'))}">${ic('edit', 's')}</button><button class="iconbtn danger" data-m="del" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></div>`).join('')
      || `<p class="muted">${esc(tr('No labels yet.'))}</p>`;
  };
  draw();
  const after = async () => { await draw(); await load(); render(); };
  md.addEventListener('click', async e => {
    const b = /** @type {HTMLElement} */ (e.target).closest('[data-m]'); if (!b) return;
    const m = b.dataset.m, x = cur.find(y => y.id === +(b.closest('[data-olbid]')?.dataset.olbid || 0));
    if (m === 'close') { md.remove(); done && done(); return; }
    try {
      if (m === 'add') { const el = /** @type {HTMLInputElement} */ (md.querySelector('#olb-new')), v = el.value.trim(); if (!v) { need(el); return; } await api('POST', '/api/org-labels', {org_id: oid, name: v}); el.value = ''; await after(); return; }
      if (!x) return;
      if (m === 'ren') { const v = await askPrompt(tr('Rename'), x.name, {ok: tr('Save')}); if (v === null || !v.trim()) return; await api('PATCH', '/api/org-labels/' + x.id, {name: v.trim()}); await after(); return; }
      if (m === 'color') { const i = LCOLORS.indexOf(x.color); await api('PATCH', '/api/org-labels/' + x.id, {color: LCOLORS[(i + 1) % LCOLORS.length]}); await after(); return; }
      if (m === 'del') { if (!await askConfirm(tr('Delete the label “{0}”?', x.name), tr('Projects that use it keep it as their own project tag.'), {ok: tr('Delete'), danger: true})) return; await api('DELETE', '/api/org-labels/' + x.id); await after(); }
    } catch { /* api() said why */ }
  });
}
