// @ts-check
/* Kalmido web client: the dialog of a custom field (fieldModal: new / edit, kinds, options, formula) (2.1156.0, #4280: moved here from projects.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// the "Status" template of a new select field (#1193): grey, blue, yellow, green out of the list colours
const LR_STATUS_TPL = [[N_('Not started'), '#94a3b8'], [N_('In progress'), '#6d8cff'], [N_('Waiting'), '#f5b041'], [N_('Done|status'), '#4ade80']];
let fdSeq = 0;
const fdDef = j => ({id: j.id, list_id: j.list_id, name: j.name, type: j.type, options: j.options || {}, pinned: j.pinned, sort: j.sort, required: !!j.required, org_field_id: j.org_field_id || null});  // 2.609.0 (#3373): + required, org_field_id
function fdCreate(lid, body, done) {
  const tmp = -1e9 - (++fdSeq), k = 'f:' + tmp;
  const nf = {id: tmp, list_id: lid, name: body.name, type: body.type, options: JSON.parse(JSON.stringify(body.options || {})), pinned: body.pinned ? 1 : 0, sort: Math.max(0, ...fieldsAll(lid).map(x => +x.sort || 0)) + 1};
  let real = null;
  const put = () => {  // again on top of a state fetched meanwhile (core.js OPT), not once the answer is there
    if (real) return null;
    if (!fieldById(tmp)) S.fields = [...(S.fields || []), nf];
    const l = listById(lid);
    if (l && Array.isArray(l.columns) && !l.columns.includes(k) && l.columns.length < 40) l.columns = [...l.columns, k];  // like the server: a list with own columns shows it last
    return () => { S.fields = (S.fields || []).filter(x => x.id !== tmp); const m = listById(lid); if (m && Array.isArray(m.columns)) m.columns = m.columns.filter(x => x !== k); };
  };
  const pr = optWrite(put, async () => {
    const j = await api('POST', `/api/lists/${lid}/fields`, body);
    real = j.id; FD_REAL.set(tmp, j.id);
    S.fields = [...(S.fields || []).filter(x => x.id !== tmp && x.id !== j.id), fdDef(j)];  // the stand-in -> the real field (with the options' ids)
    const l = listById(lid);
    if (l && Array.isArray(l.columns)) l.columns = l.columns.includes('f:' + j.id) ? l.columns.filter(x => x !== k) : l.columns.map(x => x === k ? 'f:' + j.id : x);
    return j;
  });
  FD_TMP.set(tmp, pr.then(j => j.id, () => null));
  done?.(nf, false);
  pr.then(async j => {
    if (j.modules_on?.length || j.type === 'formula') { try { await load(); } catch { /* offline: the next load */ } }  // the module switched on / the computed values
    render(); done?.(fieldById(j.id) || fdDef(j), true);
    let id = j.id;
    histAdd({label: tr('New field') + ': ' + qn(j.name), lids: [lid], ...(j.undo_group ? {srv: true} : {}),  // 2.809.0 (#5476): the server lists the step
      undo: async () => { await api('DELETE', '/api/fields/' + id); return {}; },
      redo: async () => { id = (await api('POST', `/api/lists/${lid}/fields`, body)).id; return {}; }});
  }, () => done?.(null, true)).finally(() => FD_TMP.delete(tmp));
  return pr;
}
function fdEdit(f, body, done) {
  const old = {name: f.name, options: JSON.parse(JSON.stringify(f.options || {})), pinned: f.pinned, required: !!f.required};
  // 2.609.0 (#3373): a field linked to the organisation's schema sends only pinned / required (name and options stay the schema's)
  const own = 'name' in body;
  const vals = {...(own ? {name: body.name} : {}), pinned: body.pinned ? 1 : 0, ...('required' in body ? {required: !!body.required} : {}),
    ...(f.type === 'formula' || !own ? {} : {options: JSON.parse(JSON.stringify(body.options || {}))})};  // a formula's options the server works out
  // 2.564.0 (#4701): the options seen go along (_prev): a list another admin changed meanwhile answers 409 with the current field
  const sel = (f.type === 'select' || f.type === 'multiselect') && body.options, seen = sel ? JSON.parse(JSON.stringify(f.options?.options || [])) : null;
  const pr = optWrite(optSet(() => fieldById(f.id), vals), () => api('PATCH', '/api/fields/' + f.id, sel ? {...body, _prev: {options: seen}} : body));
  done?.(fieldById(f.id), false);
  pr.then(async j => {
    const x = fieldById(f.id); if (x && j?.id) Object.assign(x, fdDef(j));
    if (f.type === 'select' || f.type === 'multiselect') {  // removed options are cleared in all tasks (the server did it)
      const keep = new Set((x?.options?.options || []).map(o => o.id));
      for (const t of S.tasks.values()) {
        const v = t.fields?.[f.id]; if (v == null) continue;
        const left = String(v).split(',').filter(i => keep.has(i)).join(',');
        if (left !== String(v)) { t.fields = {...t.fields}; if (left && f.type === 'multiselect') t.fields[f.id] = left; else delete t.fields[f.id]; }
      }
    }
    if (f.type === 'formula') { try { await load(); } catch { /* offline */ } }  // the computed values
    render(); done?.(fieldById(f.id), true);
    /** @type {any} */
    const back = own ? {name: old.name, pinned: !!old.pinned, options: old.options, ...(f.type === 'formula' ? {formula: old.options.formula || ''} : {})} : {pinned: !!old.pinned};
    if ('required' in body) back.required = old.required;
    const now = sel ? JSON.parse(JSON.stringify(x?.options?.options || [])) : null;  // what the server stored (undo / redo say what they saw)
    const go = (b, p) => async () => { await api('PATCH', '/api/fields/' + f.id, sel ? {...b, _prev: {options: p}} : b); return {}; };
    histAdd({label: tr('Edit field') + ': ' + qn(old.name), lids: [f.list_id], undo: go(back, now), redo: go(body, seen), ...(j?.undo_group ? {srv: true} : {})});  // 2.809.0 (#5476)
  }, e => {
    const x = fieldById(f.id); if (e?.status === 409 && e.data?.field && x) { Object.assign(x, fdDef(e.data.field)); render(); }  // the current state, not ours
    done?.(fieldById(f.id), true);
  });
  return pr;
}
// 2.609.0 (#3373): ep = the routes of a field of the organisation's schema {post, one: id => url, noType: [types]} instead of
// the list's; a field linked to the schema (f.org_field_id) keeps its name and options here (pinned / required only)
function fieldModal(lid, f, done, ep) {
  const edit = !!f, linked = !ep && !!f?.org_field_id, st = {type: f?.type || 'text', opts: JSON.parse(JSON.stringify(f?.options?.options || [{id: '', name: '', color: LCOLORS[1]}])), stages: !!f?.options?.stages};  // 2.410.0 A (#3514): + stages
  /** @type {any} */
  const md = modal(`<h3>${edit ? tr('Edit field') : tr('New field')}</h3>
    ${linked ? `<div class="shint keep ofslinked">${esc(tr('This field comes from the organisation: its name and options are changed there, for every project.'))}</div>` : ''}
    <div class="row"><label for="fd-name">${tr('Name')}</label><input id="fd-name" value="${esc(f?.name || '')}" maxlength="60" placeholder="${tr('e.g. Budget, Stage, Client')}" ${linked ? 'readonly' : ''}></div>
    <div class="row"><label for="fd-type">${tr('Type')}</label><select id="fd-type" ${edit ? 'disabled' : ''}>${FTYPES.filter(([k]) => !ep?.noType?.includes(k)).map(([k, n]) => `<option value="${k}" ${st.type === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div id="fd-extra" ${linked ? 'hidden' : ''}></div>
    <div class="row" id="fd-reqrow" ${ep || ['formula', 'checkbox'].includes(st.type) ? 'hidden' : ''}><label>${tr('Required')}</label><label class="chkl"><input type="checkbox" id="fd-req" ${f?.required ? 'checked' : ''}> ${tr('a new task needs a value')}</label></div>
    <div class="row" ${colCfg(lid) || ep ? 'hidden' : ''}><label>${tr('Task rows')}</label><label class="chkl"><input type="checkbox" id="fd-pin" ${f?.pinned ? 'checked' : ''}> ${tr('show in the task row (at most 2 fields)')}</label></div>
    ${colCfg(lid) ? `<div class="shint keep lrcolhint">${tr('Whether the field shows in the task row is set in {0}.', `<button type="button" class="linkbtn" data-m="fd-cols">${esc(tr('Shown fields'))}</button>`)}</div>` : ''}
    <div class="foot">${edit ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  const extra = () => {
    const x = $('#fd-extra', md);
    if (st.type === 'formula') { x.innerHTML = fxModalExtra(lid, f); return; }  // 2.43.0 (#1328)
    if (['currency', 'rating', 'task'].includes(st.type)) { x.innerHTML = ''; cfkModalExtra(x, st.type, f); return; }  // 2.156.0 B (#2069): cfkinds.js, on demand
    if (st.type === 'number') x.innerHTML = `<div class="row"><label for="fd-unit">${tr('Unit')}</label><input id="fd-unit" value="${esc(f?.options?.unit || '')}" maxlength="12" placeholder="${tr('optional, e.g. € or h')}" style="max-width:8.75rem"></div>`;
    // 2.40.0 (#1193): a palette per option instead of cycling, a handle to drag (Alt+↑/↓), the Status template for a new field
    else if (st.type === 'select' || st.type === 'multiselect') x.innerHTML = `<h4>${tr('Options')}</h4>${edit ? '' : `<div class="row lrtpl"><button type="button" class="btn sm" data-m="opt-tpl" title="${esc(tr('Not started, In progress, Waiting, Done'))}">${ic('list', 's')} ${tr('Template “Status”')}</button><button type="button" class="btn sm" data-m="opt-empty">${tr('Start empty')}</button></div>`}<div class="optlist" role="list">${st.opts.map((o, i) => `<div class="optrow" data-i="${i}" role="listitem"><span class="colh" data-oh="${i}" title="${esc(tr('Drag to reorder'))}" aria-hidden="true">${ic('grip', 's')}</span><button type="button" class="swc" data-ocol="${i}" style="background:${cssColor(o.color) || 'var(--bg4)'}" title="${tr('Colour')}" aria-label="${esc(tr('Colour'))}" aria-expanded="${st.pal === i}"></button><input data-oname="${i}" value="${esc(o.name)}" maxlength="60" placeholder="${tr('Option')}" title="${esc(tr('Alt+↑ / Alt+↓ moves the option'))}">${st.type === 'select' && st.stages ? cfst_optSel(o, i) : ''}<button type="button" class="iconbtn" data-orm="${i}" title="${tr('Remove')}">${ic('x', 's')}</button></div>${st.pal === i ? `<div class="colors lrpal" role="group" aria-label="${esc(tr('Colour'))}">${LCOLORS.map((c, k) => `<button type="button" data-opal="${esc(c)}" style="background:${c || 'var(--bg4)'}" class="${(o.color || '') === c ? 'on' : ''}" aria-pressed="${(o.color || '') === c}" aria-label="${esc(c ? tr('Colour {0}', k) : tr('No colour'))}"></button>`).join('')}</div>` : ''}`).join('')}</div><button class="btn sm" data-m="opt-add">${ic('plus', 's')} ${tr('Option')}</button>${edit ? `<div class="shint keep">${tr('Removing an option clears it in all tasks.')}</div>` : ''}${st.type === 'select' ? cfst_dlgRow(st) : ''}`;
    else x.innerHTML = st.type === 'person' ? `<div class="shint keep">${tr('Select the owner or a member of the project.')}</div>` : '';
  };
  extra();
  md.addEventListener('change', (/** @type {any} */ e) => {
    if (e.target.id === 'fd-type') { st.type = e.target.value; extra(); const rr = $('#fd-reqrow', md); if (rr) rr.hidden = !!ep || ['formula', 'checkbox'].includes(st.type); }  // 2.609.0 (#3373)
    if (e.target.id === 'fd-stages') { st.stages = e.target.checked; st.pal = null; extra(); $('#fd-stages', md)?.focus(); }  // 2.410.0 A (#3514)
    if (e.target.dataset?.osp !== undefined) st.opts[+e.target.dataset.osp].special = e.target.value;
  });
  md.addEventListener('input', (/** @type {any} */ e) => { const i = e.target.dataset.oname; if (i !== undefined) st.opts[+i].name = e.target.value; });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.ocol !== undefined) { st.pal = st.pal === +b.dataset.ocol ? null : +b.dataset.ocol; extra(); $(`[data-ocol="${b.dataset.ocol}"]`, md)?.focus(); return; }
    if (b.dataset.opal !== undefined) { const i = st.pal; st.opts[i].color = b.dataset.opal; st.pal = null; extra(); $(`[data-ocol="${i}"]`, md)?.focus(); return; }
    if (b.dataset.orm !== undefined) { st.opts.splice(+b.dataset.orm, 1); st.pal = null; extra(); return; }
    const a = b.dataset.m;
    if (a === 'opt-tpl' || a === 'opt-empty') { st.pal = null; st.opts = a === 'opt-tpl' ? LR_STATUS_TPL.map(([n, c]) => ({id: '', name: tr(n), color: c})) : [{id: '', name: '', color: LCOLORS[1]}]; extra(); return; }
    if (a === 'opt-add') { st.opts.push({id: '', name: '', color: LCOLORS[(st.opts.length % (LCOLORS.length - 1)) + 1]}); extra(); $$('[data-oname]', md).pop()?.focus(); return; }
    if (a === 'close') { md.remove(); return; }
    if (a === 'fd-cols') { colModal(lid); return; }  // 2.40.0 (#1429): own columns decide what the rows show
    if ((a === 'del' || a === 'save') && edit && f.id < 0) { await fdReal(f.id); f = fieldById(FD_REAL.get(f.id)) || f; if (f.id < 0) return; }  // 2.554.0 B (#4658): a field still on its way: its real id first
    if (a === 'del') {
      // 2.40.0 (#1192): the server counts every task with a value (also those not loaded here); the local count if offline
      if (ep) {  // 2.609.0 (#3373): the projects keep their linked fields as plain ones
        if (!await askConfirm(tr('Delete the field “{0}”?', f.name), tr('Projects that use it keep it as their own field, with its values.'), {ok: tr('Delete'), danger: true})) return;
        try { await api('DELETE', ep.one(f.id)); } catch { return; }
        md.remove(); done && done(); return;
      }
      const fc = await api('GET', `/api/fields/${f.id}/count`).catch(() => null), n = fc ? fc.tasks : [...S.tasks.values()].filter(t => t.fields?.[f.id] != null).length;  // 2.552.0 (#4561 B12): + moved
      if (!await askConfirm(tr('Delete the field “{0}”?', f.name), tr('The field goes into the trash with its values; the project settings can restore it.') + (n ? ' ' + trn('({0} task with a value)', '({0} tasks with a value)', n) : '') + fdMovedWarn(fc) + fxUsedWarn(f.id), {ok: tr('Delete'), danger: true})) return;
      md.remove(); fdDelete(f, done); return;  // 2.554.0 B (#4658): gone at once, the server follows (fdDelete); 2.550.0 (#4528): into the trash, Undo restores it
    }
    if (a === 'save') {
      const name = $('#fd-name', md).value.trim(); if (!name) { need($('#fd-name', md)); return; }
      /** @type {any} */
      const options = st.type === 'number' ? {unit: $('#fd-unit', md).value.trim()} : st.type === 'select' || st.type === 'multiselect' ? {options: st.opts.filter(o => o.name.trim()), ...(st.type === 'select' ? {stages: st.stages} : {})} : cfkModalOpts(md, st.type);  // 2.156.0 B (#2069)
      /** @type {any} */
      let body = {name, options, pinned: $('#fd-pin', md).checked};
      if (st.type === 'formula') Object.assign(body, fxModalBody(md));  // 2.43.0 (#1328): the server checks it (position / field name)
      if (!ep && !['formula', 'checkbox'].includes(st.type)) body.required = $('#fd-req', md).checked;  // 2.609.0 (#3373)
      if (linked) body = {pinned: body.pinned, required: body.required};
      if (ep) { delete body.pinned; if (!edit) Object.assign(body, ep.extra || {}); }
      if (ep) { try { await api(edit ? 'PATCH' : 'POST', edit ? ep.one(f.id) : ep.post, edit ? body : {...body, type: st.type}); } catch { return; } md.remove(); done && done(); return; }
      // 2.554.0 B (#4658): the dialog closes and the field shows at once (fdCreate / fdEdit); offline it stays open (fields need the server)
      // what the server would refuse is said here, the dialog stays: a selection without options, a third pinned field, field 21
      if (!OUT.online) { toast(tr('Offline: only works again with a connection')); return; }
      if ((st.type === 'select' || st.type === 'multiselect') && !options.options.length) { toast(tr('A selection field needs at least one option')); return; }
      if (body.pinned && !(edit && f.pinned) && fieldsAll(lid).filter(x => x.pinned && x.id !== f?.id).length >= 2) { toast(tr('At most {0} fields can be shown on the task rows', 2)); return; }
      if (!edit && fieldsAll(lid).length >= 20) { toast(tr('At most {0} fields per project', 20)); return; }
      const pr = edit ? fdEdit(f, body, done) : fdCreate(lid, {...body, type: st.type}, done);
      if (st.type === 'formula') { try { await pr; } catch { return; } }  // only the server reads a formula: the dialog stays open until it took it (an error names the position)
      md.remove();
    }
  });
  const optMove = (i, j) => {  // #1193: option i to place j (the order is the order of the select and of sorting by the field)
    if (j < 0 || j >= st.opts.length || i === j) return;
    const [o] = st.opts.splice(i, 1); st.opts.splice(j, 0, o); st.pal = null; extra();
  };
  md.addEventListener('keydown', (/** @type {any} */ e) => {
    const i = e.target.dataset?.oname; if (i === undefined || !e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
    e.preventDefault(); const j = +i + (e.key === 'ArrowUp' ? -1 : 1); if (j < 0 || j >= st.opts.length) return;
    optMove(+i, j); $(`[data-oname="${j}"]`, md)?.focus();
  });
  md.addEventListener('pointerdown', (/** @type {any} */ e) => {  // drag the handle (mouse, pen, touch), like "Shown fields"
    const h = e.target.closest('[data-oh]'); if (!h) return;
    e.preventDefault();
    const ls = $('.optlist', md), row = h.closest('.optrow'), from = +row.dataset.i;
    if (st.pal != null) { st.pal = null; ls.querySelector('.lrpal')?.remove(); }
    row.classList.add('drag');
    const mv = rafThrottle(ev => {  // 2.87.9 (#1965): once per frame
      const rows = [...ls.querySelectorAll('.optrow')];
      const over = rows.find(r => { const bx = r.getBoundingClientRect(); return r !== row && ev.clientY >= bx.top && ev.clientY < bx.bottom; });
      if (!over) return;
      ls.insertBefore(row, rows.indexOf(over) > rows.indexOf(row) ? over.nextSibling : over);
    });
    const up = () => {
      document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); document.removeEventListener('pointercancel', up);
      mv.flush();
      const to = [...ls.querySelectorAll('.optrow')].indexOf(row);
      if (to !== from) optMove(from, to); else { row.classList.remove('drag'); }
    };
    document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up); document.addEventListener('pointercancel', up);
  });
  setTimeout(() => $('#fd-name', md).focus(), 50);
}
