/* Kalmido web client: lists like a table (2.39.1). #1217: move a column by dragging its title (owner / list admins,
   mouse and pen; phones keep "Shown fields…"). #1327: edit custom field cells right in the row (desktop). */

// ---- 2.39.1 (#1217): drag a column title left / right; an accent line shows where it goes. The order is the list's
// "columns" (the same as in "Shown fields…", saved for everyone, with undo); the title column stays in front. A click
// without moving still sorts (the click after a drag is swallowed).
let tcMoved = 0;
document.addEventListener('pointerdown', e => {
  const b = e.target.closest?.('.lchead .lcs[data-colsort]'); if (!b || e.button !== 0 || e.pointerType === 'touch' || isTouch()) return;
  const head = b.closest('.lchead'), l = listById(+head.dataset.lid); if (!l || !canManage(l) || !Array.isArray(l.columns)) return;
  const cell = b.closest('.lc'), k = cell.dataset.k, x0 = e.clientX, y0 = e.clientY;
  let on = false, guide = null, to = null;
  const cells = () => [...head.querySelectorAll('.lc[data-k]')].filter(c => c.getClientRects().length);
  const mv = ev => {
    if (!on) { if (Math.abs(ev.clientX - x0) < 6 && Math.abs(ev.clientY - y0) < 6) return; on = true; cell.classList.add('lcmove'); document.body.classList.add('lcmoving'); }
    // the gap nearest to the pointer: before cell i (i = cells.length: after the last)
    const cs = cells(), xs = cs.map(c => c.getBoundingClientRect());
    let best = 0, bd = Infinity;
    for (let i = 0; i <= cs.length; i++) {
      const x = i < cs.length ? xs[i].left - 6 : xs[cs.length - 1].right + 6, d = Math.abs(ev.clientX - x);
      if (d < bd) { bd = d; best = i; }
    }
    to = best < cs.length ? cs[best].dataset.k : null;
    const gx = best < cs.length ? xs[best].left - 6 : xs[cs.length - 1].right + 6;
    guide = lcGuide(cell, guide, gx);
  };
  const up = () => {
    document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); document.removeEventListener('pointercancel', up);
    guide?.remove(); cell.classList.remove('lcmove'); document.body.classList.remove('lcmoving');
    if (!on) return;
    tcMoved = Date.now();
    const next = tcColMove(l.columns, k, to);
    if (next) colSave(l.id, next);
  };
  document.addEventListener('pointermove', mv);
  document.addEventListener('pointerup', up);
  document.addEventListener('pointercancel', up);
});
// the click that ends a drag does not sort
document.addEventListener('click', e => {
  if (tcMoved && Date.now() - tcMoved < 400 && e.target.closest?.('.lchead')) { e.preventDefault(); e.stopPropagation(); }
  tcMoved = 0;
}, true);
// cols with k moved in front of the key `before` (null = to the end); the task number stays first; null = no change
function tcColMove(cols, k, before) {
  if (!Array.isArray(cols) || !cols.includes(k) || k === before) return null;
  const rest = cols.filter(x => x !== k);
  let i = before == null ? rest.length : rest.indexOf(before);
  if (i < 0) return null;
  if (rest[0] === 'id' && i === 0) i = 1;
  rest.splice(i, 0, k);
  return JSON.stringify(rest) === JSON.stringify(cols) ? null : rest;
}

// ---- 2.39.1 (#1327): custom field cells are edited right in the row (desktop, with the right to change the task):
// number / text / link = a field in the cell (Enter or a click next to it saves, Esc cancels, Tab = the next cell of the
// row), choice = a menu with the option colours, person = a menu of the list's people, date = the calendar, checkbox =
// toggles. Saved like every other change (at once on screen, back on an error, Ctrl+Z). Touch screens: in the task.
const TC_INPUT = ['number', 'text', 'url'];
const tcField = k => k.startsWith('f:') ? fieldById(+k.slice(2)) : null;
const tcOk = t => !!t && t.id > 0 && !isTouch() && canEdit(t);
function tcAttr(k, t) {  // the attributes of an editable field cell (render.js lcCell row)
  const f = tcField(k); if (!f || !tcOk(t) || f.type === 'formula') return sgAttr(k, t);  // 2.43.0 (#1328): formulas are computed; (#1331): any cell takes the focus
  const v = t.fields?.[f.id], txt = fieldText(f, v, t.list_id);
  return ` data-fe="${f.id}" data-tid="${t.id}" tabindex="0" role="button" aria-label="${esc(f.name + ': ' + (txt || tr('empty')))}"`;
}
function tcVal(f, raw) {  // typed text -> the stored value (null = empty)
  let v = (raw || '').trim() || null;
  if (v && f.type === 'url' && !/^https?:\/\//i.test(v) && /^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(v)) v = 'https://' + v;
  if (v && f.type === 'number') v = numIn(v);
  return v;
}
async function tcSave(tid, fid, v) {
  const t = taskById(tid); if (!t) return;
  const old = t.fields?.[fid] ?? null;
  if (old === v) { render(); return; }
  const before = snapTask(t), put = x => { const y = taskById(tid); if (!y) return; y.fields = {...(y.fields || {})}; if (x == null) delete y.fields[fid]; else y.fields[fid] = x; };
  put(v); render();  // at once on screen; the server's answer (or the error) settles it
  try {
    const r = await api('PATCH', '/api/tasks/' + tid, {fields: {[fid]: v}});
    putTask(r); render(); if (S.sel === tid) renderDetail();
    const after = S.tasks.get(tid) || r;
    if (before) histFields(histLabel(before, after), [[before, snapTask(after)]], {res: r});
  } catch { put(old); render(); }  // api() already said what went wrong
}
function tcCells(tid) { return [...(document.getElementById('tc-' + tid)?.querySelectorAll('.lc[data-fe]') || [])].filter(c => c.getClientRects().length); }
function tcNext(tid, fid, dir) {  // Tab: the next editable cell of the row (after the re-render)
  const cs = tcCells(tid), i = cs.findIndex(c => +c.dataset.fe === fid), n = cs[i + dir];
  if (!n) { document.getElementById('tc-' + tid)?.closest('.trow')?.focus?.({preventScroll: true}); return; }
  const f = fieldById(+n.dataset.fe);
  if (f && TC_INPUT.includes(f.type)) tcEdit(n); else n.focus({preventScroll: true});
}
function tcEdit(cell) {
  const t = taskById(+cell.dataset.tid), f = fieldById(+cell.dataset.fe); if (!t || !f || !tcOk(t) || cell.querySelector('.tcin')) return;
  const v = t.fields?.[f.id] ?? null, put = x => sgMultiPut('f:' + f.id, x) || tcSave(t.id, f.id, x);  // 2.43.0 (#1331): a range takes the pick
  if (f.type === 'checkbox') { put(v === '1' ? null : '1'); return; }
  if (f.type === 'date') { dpOpen(cell, {kind: 'date', value: v || '', label: f.name, onPick: d => put(d || null)}); return; }
  if (f.type === 'select' || f.type === 'person') {
    const opts = f.type === 'select' ? (f.options?.options || []).map(o => ({label: o.name, swc: o.color || '', on: v === o.id, fn: () => put(o.id)}))
      : listPeople(listById(t.list_id)).map(p => ({label: p.name, icon: 'user', on: String(p.user_id) === v, fn: () => put(String(p.user_id))}));
    menu(cell, [{label: f.name, dis: true, cls: 'mhead'}, '-', ...opts, ...(v != null || sgMulti() ? ['-', {label: tr('Empty the field'), icon: 'x', fn: () => put(null)}] : [])]);
    return;
  }
  const shown = v == null ? '' : f.type === 'number' ? (+v).toLocaleString(LOCALE(), {useGrouping: false, maximumFractionDigits: 6}) : v;
  cell.classList.add('tcon');
  cell.innerHTML = `<input class="tcin" ${f.type === 'number' ? 'inputmode="decimal"' : f.type === 'url' ? 'type="url" inputmode="url"' : 'maxlength="1000"'} value="${esc(shown)}" aria-label="${esc(f.name)}" autocomplete="off">${f.type === 'number' && f.options?.unit ? `<span class="tcu">${esc(f.options.unit)}</span>` : ''}`;
  const inp = cell.querySelector('.tcin');
  let done = false;
  const fin = (save, dir) => {
    if (done) return; done = true;
    if (save) { tcSave(t.id, f.id, tcVal(f, inp.value)).then(() => { if (dir) tcNext(t.id, f.id, dir); }); }
    else { render(); setTimeout(() => tcCells(t.id).find(c => +c.dataset.fe === f.id)?.focus({preventScroll: true}), 0); }
  };
  inp.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); fin(true); setTimeout(() => tcCells(t.id).find(c => +c.dataset.fe === f.id)?.focus({preventScroll: true}), 0); }
    else if (e.key === 'Escape') { e.preventDefault(); fin(false); }
    else if (e.key === 'Tab') { e.preventDefault(); fin(true, e.shiftKey ? -1 : 1); }
  });
  inp.addEventListener('blur', () => fin(true));
  inp.focus(); inp.select();
}
// a click on an editable cell edits it (instead of opening the task); clicks inside the open field stay there
document.addEventListener('click', e => {
  const c = e.target.closest?.('.lcols .lc[data-fe]'); if (!c) return;
  if (e.target.closest('a[href]')) return;  // a link value opens the link as before (Enter / F2 on the cell edits it)
  e.preventDefault(); e.stopPropagation();
  if (!e.target.closest('.tcin')) tcEdit(c);
}, true);
document.addEventListener('dblclick', e => { if (e.target.closest?.('.lcols .lc[data-fe]')) e.stopPropagation(); }, true);
document.addEventListener('keydown', e => {
  const c = e.target.closest?.('.lcols .lc[data-fe]'); if (!c || e.target.closest('.tcin') || e.altKey || e.ctrlKey || e.metaKey) return;
  if (e.key === 'Enter' || e.key === ' ' || e.key === 'F2') { e.preventDefault(); e.stopPropagation(); tcEdit(c); }
}, true);
// sorting by a column without any value: say so instead of a silent nothing (#1327)
document.addEventListener('click', e => {
  const b = e.target.closest?.('.lchead [data-colsort]'); if (!b) return;
  const l = routeList(), k = b.dataset.colsort; if (!l) return;
  const ts = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.deleted_at && t.id > 0);
  const has = k.startsWith('f:') ? ts.some(t => t.fields?.[k.slice(2)] != null && t.fields[k.slice(2)] !== '')
    : k === 'due' ? ts.some(t => t.due) : k === 'prio' ? ts.some(t => t.priority) : k === 'tags' ? ts.some(t => (t.tags || []).length || (t.ltags || []).length) : true;
  if (!has) toast(tr('No values in this column yet: the order stays the same'));
});

// ---- 2.39.1 (#1327): "Shown fields…" adds, changes and deletes custom fields (owner / list admins). With the module
// "Custom fields" off, adding a field switches it on (the server does so for the list's owner, here for whoever adds it)
function tcFieldBtns(k, name) {
  return `<button type="button" class="iconbtn colfe" data-colfe="${esc(k.slice(2))}" title="${esc(tr('Rename or change the field'))}" aria-label="${esc(tr('Rename or change the field') + ': ' + name)}">${ic('edit', 's')}</button>` +
    `<button type="button" class="iconbtn colfd" data-colfd="${esc(k.slice(2))}" title="${esc(tr('Delete field'))}" aria-label="${esc(tr('Delete field') + ': ' + name)}">${ic('trash', 's')}</button>`;
}
async function tcFieldAct(l, b, resync) {
  const f = fieldById(+(b.dataset.colfe || b.dataset.colfd)); if (!f) return;
  if (b.dataset.colfe) { fieldModal(l.id, f, () => resync(null, 'f:' + f.id)); return; }
  const n = [...S.tasks.values()].filter(t => t.fields?.[f.id] != null).length;
  if (!await askConfirm(tr('Delete the field “{0}”?', f.name), tr('Its values are deleted in all tasks.') + (n ? ' ' + trn('({0} task with a value)', '({0} tasks with a value)', n) : '') + fxUsedWarn(f.id), {ok: tr('Delete'), danger: true})) return;
  try { await api('DELETE', '/api/fields/' + f.id); } catch { return; }
  await load(); render(); resync();
}
function tcFieldAdd(l, resync) {
  const had = new Set(fieldsAll(l.id).map(f => f.id)), off = !fieldsOn();
  fieldModal(l.id, null, async () => {
    if (off && !fieldsOn()) { try { await api('PATCH', '/api/settings', {features: [...(S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean), 'fields'].join(',')}); } catch { /* the server said why */ } }
    if (off) { try { await load(); } catch { /* offline */ } render(); toast(tr('Custom fields are switched on now (Settings > Modules)')); }
    const nf = fieldsAll(l.id).find(f => !had.has(f.id)); if (!nf) { resync(); return; }
    const k = 'f:' + nf.id, cur = listById(l.id);
    if (cur && !(Array.isArray(cur.columns) && cur.columns.includes(k))) {  // shown at once: the list's columns with the new field
      const base = Array.isArray(cur.columns) ? cur.columns : colDefault(cur).filter(x => x === 'id' || colChoices(cur).some(y => y[0] === x));
      await colSave(l.id, [...base.filter(x => x !== k), k], true);
    }
    resync(k, k);
  });
}
