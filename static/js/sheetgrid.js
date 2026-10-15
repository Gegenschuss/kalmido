/* Kalmido web client: a list like a spreadsheet (2.43.0, #1331), desktop with a fine pointer. One active cell (accent
   frame): arrow keys, Tab / Shift+Tab, Enter = edit, Esc = cancel, typing overwrites; Shift+click / Shift+arrows / dragging
   select a range that is changed at once (type a value, Delete empties it), copied as a table (TSV + HTML), filled down
   (Ctrl/Cmd+D or the handle at the corner) and pasted into from Sheets / Excel with a preview (more rows than tasks = new
   tasks). Due date and assignee are set right in their cells. Every action is one undo step and one batch request.
   Phones keep "tap a cell = edit" (tablecells.js). Keys only act while a cell has the focus (the list keys stay as they are). */

const SG = {a: null, f: null, nr: null, moved: 0};  // a = anchor, f = active cell {tid, k}; nr = the new row below the last one
const SG_PASTE = ['title', 'due', 'who'];             // besides custom fields (no formula)
const sgOn = () => !isTouch();
function sgAttr(k, t) {  // tablecells.js tcAttr: every other cell of a real task can take the focus (not in the Tab order)
  return t && t.id > 0 && sgOn() ? ` tabindex="-1"${k === 'due' || k === 'who' ? ` data-sgk="${k}"` : ''}` : '';
}
// ---- the grid: the shown rows with columns and their cells (the title counts as the first column)
function sgRows() { return [...document.querySelectorAll('#view .trow[data-id]')].filter(r => +r.dataset.id > 0 && r.querySelector('.lcols') && r.getClientRects().length); }
function sgKeys(row) { return ['title', ...[...(row?.querySelectorAll('.lcols .lc[data-k]') || [])].filter(c => c.getClientRects().length).map(c => c.dataset.k)]; }
function sgEl(tid, k) {
  const row = document.querySelector(`#view .trow[data-id="${tid}"]`); if (!row) return null;
  return k === 'title' ? row.querySelector('.tmain .ttl') : row.querySelector(`.lcols .lc[data-k="${CSS.escape(k)}"]`);
}
function sgCellOf(el) {
  if (!el?.closest) return null;
  const lc = el.closest('#view .lcols .lc[data-k]');
  if (lc) { const tid = +lc.closest('.lcols').id.slice(3); return tid > 0 ? {tid, k: lc.dataset.k} : null; }
  const ttl = el.closest('#view .trow[data-id] .tmain .ttl'), row = ttl?.closest('.trow');
  return ttl && row.querySelector('.lcols') && +row.dataset.id > 0 ? {tid: +row.dataset.id, k: 'title'} : null;
}
function sgPos(c) {  // {r, c} of a cell in the grid (null when gone)
  const rows = sgRows(), r = rows.findIndex(x => +x.dataset.id === c?.tid); if (r < 0) return null;
  const i = sgKeys(rows[r]).indexOf(c.k); return i < 0 ? null : {r, c: i, rows};
}
function sgRange() {  // the selected cells [{tid, k}] (rectangle anchor..active), at least the active one
  if (!SG.f) return [];
  const p = sgPos(SG.f), q = SG.a ? sgPos(SG.a) : p; if (!p) return [];
  if (!q) return [SG.f];
  const keys = sgKeys(p.rows[p.r]), out = [];
  for (let r = Math.min(p.r, q.r); r <= Math.max(p.r, q.r); r++)
    for (let c = Math.min(p.c, q.c); c <= Math.max(p.c, q.c); c++) out.push({tid: +p.rows[r].dataset.id, k: keys[c], r, c});
  return out;
}
const sgMulti = () => sgRange().length > 1;
// ---- painting: the active cell (accent frame), the range, the fill handle; again after every re-render of the view
function sgPaint() {
  document.querySelectorAll('#view .sgact,#view .sgsel').forEach(x => x.classList.remove('sgact', 'sgsel'));
  document.querySelectorAll('#view .sgfill').forEach(x => x.remove());
  if (!SG.f) return;
  const rg = sgRange(); if (!rg.length) return;
  if (rg.length > 1) for (const c of rg) sgEl(c.tid, c.k)?.classList.add('sgsel');
  const el = sgEl(SG.f.tid, SG.f.k); if (!el) return;
  el.classList.add('sgact');
  const t = taskById(SG.f.tid);
  if (t && canEdit(t) && SG.f.k !== 'title' && sgKind(SG.f.k)) el.insertAdjacentHTML('beforeend', `<span class="sgfill" data-sgfill title="${esc(tr('Drag down to fill (Ctrl+D)'))}" aria-hidden="true"></span>`);
}
function sgFocus(c, extend) {
  if (!c) return;
  if (!extend) SG.a = c;
  SG.f = c; SG.via = Date.now();  // a title is a cell only when the grid moved there (j / k / x / e on rows stay as they are)
  const el = sgEl(c.tid, c.k);
  if (el) { el.focus({preventScroll: true}); el.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
  sgPaint();
}
function sgClear() { SG.a = SG.f = null; sgPaint(); }
let sgObsT = 0;
const sgObs = new MutationObserver(() => {
  if (!SG.f && !SG.nr) return;
  cancelAnimationFrame(sgObsT);
  sgObsT = requestAnimationFrame(() => {
    if (SG.nr) sgNewMount();
    if (!SG.f) return;
    const el = sgEl(SG.f.tid, SG.f.k);
    if (!el) { if (!document.querySelector(`#view .trow[data-id="${SG.f.tid}"]`)) sgClear(); return; }
    if (!el.classList.contains('sgact')) sgPaint();
    const ae = document.activeElement;  // a re-render took the focus away from the active cell: back to it
    if ((!ae || ae === document.body) && Date.now() - SG.moved < 4000) el.focus({preventScroll: true});
  });
});
document.addEventListener('DOMContentLoaded', () => { const v = $('#view'); if (v) sgObs.observe(v, {childList: true, subtree: true}); });
if (document.readyState !== 'loading') setTimeout(() => { const v = $('#view'); if (v) sgObs.observe(v, {childList: true, subtree: true}); }, 0);
document.addEventListener('focusin', e => {
  if (!sgOn()) return;
  const c = sgCellOf(e.target);
  if (c && c.k === 'title' && !(SG.via && Date.now() - SG.via < 300) && !(SG.f && SG.f.tid === c.tid && SG.f.k === 'title')) { if (SG.f) sgClear(); return; }
  if (c && e.target === sgEl(c.tid, c.k)) {
    if (!SG.f || SG.f.tid !== c.tid || SG.f.k !== c.k) { if (!SG.drag) SG.a = c; SG.f = c; sgPaint(); }
  } else if (SG.f && !e.target.closest?.('.tcin,.ttlin,.sgin,#pop,#dpop,.modal')) sgClear();
});

// ---- what a column holds: the kind of value, how a value reads, how typed / pasted text becomes a value
function sgKind(k) {
  if (k === 'title' || k === 'due' || k === 'who') return k;
  const f = k.startsWith('f:') ? fieldById(+k.slice(2)) : null;
  return f && f.type !== 'formula' ? 'f' : null;
}
function sgGet(t, k) {  // the stored value of a cell
  if (k === 'title') return t.title;
  if (k === 'due') return t.due || null;
  if (k === 'who') return t.assignee_id || null;
  return t.fields?.[k.slice(2)] ?? null;
}
function sgText(t, k) {  // how the cell reads (copy)
  if (k === 'title') return mdPlain(t.title || '');
  if (k === 'due') return t.due || '';
  if (k === 'who') return t.assignee_id ? personName(t.list_id, t.assignee_id) || '' : '';
  if (k.startsWith('f:')) { const f = fieldById(+k.slice(2)); return f ? (f.type === 'url' || f.type === 'text' ? t.fields?.[f.id] || '' : f.type === 'number' || f.type === 'formula' ? (t.fields?.[f.id] != null ? (+t.fields[f.id]).toLocaleString(LOCALE(), {useGrouping: false, maximumFractionDigits: 6}) : '') : fieldText(f, t.fields?.[f.id], t.list_id)) : ''; }
  return (sgEl(t.id, k)?.textContent || '').trim();
}
function sgDay(s) {  // 2026-10-15, 15.10.2026, 15.10.26, 10/15/2026 -> YYYY-MM-DD (null = not a date)
  s = s.trim(); let y, m, d, x;
  if ((x = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/))) [y, m, d] = [+x[1], +x[2], +x[3]];
  else if ((x = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$/))) [d, m, y] = [+x[1], +x[2], +x[3]];
  else if ((x = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/))) [m, d, y] = [+x[1], +x[2], +x[3]];
  else return null;
  if (y < 100) y += 2000;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d ? dt.toISOString().slice(0, 10) : null;
}
// text -> {v} or {err}: the same rules as a single cell (server checks again)
function sgParse(t, k, raw) {
  const s = String(raw ?? '').trim();
  if (k === 'title') return s ? {v: s.replace(/\s+/g, ' ').slice(0, 500)} : {err: tr('Title missing')};
  if (!s) return {v: null};
  if (k === 'due') { const d = sgDay(s); return d ? {v: d} : {err: tr('Date expected')}; }
  if (k === 'who') {
    const p = listPeople(listById(t?.list_id ?? SG.lid)).find(x => x.name.toLowerCase() === s.toLowerCase() || (x.username || '').toLowerCase() === s.toLowerCase());
    return p ? {v: p.user_id} : {err: tr('Not a member of the list')};
  }
  const f = fieldById(+k.slice(2)); if (!f) return {err: tr('Unknown field')};
  switch (f.type) {
    case 'number': { const v = numIn(s); return v !== '' && Number.isFinite(+v) ? {v: String(+v)} : {err: tr('Number expected')}; }
    case 'date': { const d = sgDay(s); return d ? {v: d} : {err: tr('Date expected')}; }
    case 'checkbox': return /^(1|x|✓|true|wahr|yes|ja|si|sí|oui|ja\.?)$/i.test(s) ? {v: '1'} : /^(0|false|falsch|no|nein|non|nee)$/i.test(s) ? {v: null} : {err: tr('Yes or no expected')};
    case 'select': { const o = (f.options?.options || []).find(x => x.name.toLowerCase() === s.toLowerCase()); return o ? {v: o.id} : {err: tr('Unknown option')}; }
    case 'person': { const p = listPeople(listById(t?.list_id ?? f.list_id)).find(x => x.name.toLowerCase() === s.toLowerCase()); return p ? {v: String(p.user_id)} : {err: tr('Not a member of the list')}; }
    case 'url': { const v = tcVal(f, s); return /^(https?|smb|file|afp|nfs|ftp):\/\//i.test(v) ? {v} : {err: tr('Web address expected')}; }
    case 'text': return {v: s.slice(0, 1000)};
  }
  return {err: tr('Cannot be set')};
}
const sgColName = (l, k) => k === 'title' ? tr('Title') : colName(l, k);

// ---- writing: changes [{tid, k, v}] -> one batch request (patch_each), one undo step
async function sgWrite(chg, label) {
  const items = {};
  for (const {tid, k, v} of chg) {
    const t = taskById(tid); if (!t || !canEdit(t) || !sgKind(k) || sgGet(t, k) === v) continue;
    const d = items[tid] || (items[tid] = {});
    if (k === 'title') d.title = v; else if (k === 'due') d.due = v; else if (k === 'who') { d.assignee_id = v; if (t.assignee_group_id) d.assignee_group_id = null; }
    else (d.fields || (d.fields = {}))[k.slice(2)] = v;
  }
  const ids = Object.keys(items).map(Number);
  if (!ids.length) return 0;
  const snaps = ids.map(id => snapTask(taskById(id)));
  let j;
  try { j = await api('POST', '/api/tasks/batch', {ids, action: 'patch_each', data: {items}}); } catch { render(); return 0; }
  if (j?.errors?.length) toast(j.errors[0]);
  // the step goes into the history at once (a quick Ctrl+Z undoes this one, not the one before): after = before + the change
  const after = b => { const d = items[b.id], a = snapTask(b); if (!d) return a; const {fields, ...rest} = d; Object.assign(a, rest);
    if (fields) { a.fields = {...(a.fields || {})}; for (const [k, v] of Object.entries(fields)) { if (v == null) delete a.fields[k]; else a.fields[k] = v; } } return a; };
  const pairs = snaps.filter(Boolean).filter(b => !(j?.skipped || []).includes(b.id)).map(b => [b, after(b)]);
  const e = histFields(label || trn('{0} cell changed', '{0} cells changed', chg.length), pairs, {res: j, fields: [...UNDO_FIELDS, 'title', 'fields']});
  if (e && !HIST.group) offerUndo(label || trn('{0} task changed', '{0} tasks changed', ids.length), e);
  await load(); render();
  return ids.length;
}
// a value for every selected cell of the active cell's column kind (typing / Delete / a menu pick with a range)
function sgSetAll(v, k0) {
  const rg = sgRange().filter(c => c.k === (k0 || SG.f?.k));
  return sgWrite(rg.map(c => ({tid: c.tid, k: c.k, v})), trn('{0} cell changed', '{0} cells changed', rg.length));
}
function sgMultiPut(k, v) {  // tablecells.js: a pick in a range applies to the range's cells of that column
  return SG.f && SG.f.k === k && sgMulti() ? sgSetAll(v, k) : null;
}
function sgEmpty() {
  const rg = sgRange().filter(c => c.k !== 'title' && sgKind(c.k));
  if (rg.length) sgWrite(rg.map(c => ({tid: c.tid, k: c.k, v: null})), trn('{0} cell emptied', '{0} cells emptied', rg.length));
}

// ---- editing a cell: fields through tablecells.js, the title inline, due = the calendar, assignee = the menu
function sgEdit(c, typed) {
  const t = taskById(c.tid), el = sgEl(c.tid, c.k); if (!t || !el) return;
  if (!canEdit(t)) { roToast(); return; }
  if (c.k === 'title') {
    inlineEditStart(t.id);
    if (typed != null && S.ie) { S.ie.v = typed; S.ie.s = S.ie.e = typed.length; const i = $('.ttlin'); if (i) { i.value = typed; i.setSelectionRange(typed.length, typed.length); } }
    SG.ttl = t.id;
    return;
  }
  if (c.k === 'due') { dpOpen(el, {kind: 'date', value: t.due || '', label: tr('Due'), onPick: d => sgMulti() ? sgSetAll(d || null, 'due') : sgWrite([{tid: t.id, k: 'due', v: d || null}], tr('Due date changed'))}); return; }
  if (c.k === 'who') { if (sgMulti()) sgWhoMenu(el, t); else assignMenu(el, t.id); return; }
  if (!el.dataset.fe) return;
  tcEdit(el);
  const inp = el.querySelector('.tcin');
  if (inp && typed != null) { inp.value = typed; inp.setSelectionRange(typed.length, typed.length); }
}
function sgWhoMenu(el, t) {
  menu(el, [{label: tr('Nobody'), icon: 'x', fn: () => sgSetAll(null, 'who')}, '-',
    ...listPeople(listById(t.list_id)).map(p => ({label: p.name, icon: 'user', fn: () => sgSetAll(p.user_id, 'who')}))]);
}
// Enter in a field of the cell: the cell below; in the last row a new row (a title field) right under it
function sgDown(tid, k) {
  const p = sgPos({tid, k}); if (!p) return;
  if (p.r < p.rows.length - 1) { sgFocus({tid: +p.rows[p.r + 1].dataset.id, k}); SG.moved = Date.now(); return; }
  sgNewOpen(tid);
}

// ---- the new row under the last one: a title field, Enter adds the task (same list and section) and opens the next
function sgNewOpen(after) {
  const t = taskById(after); if (!t || !canAddTo(t.list_id)) return;
  SG.nr = {after, lid: t.list_id, sec: t.section_id ?? null, parent: t.parent_id || null, v: ''};
  sgNewMount(true);
}
function sgNewMount(focus) {
  const nr = SG.nr; if (!nr) return;
  let box = document.querySelector('#view .sgnew');
  const row = document.querySelector(`#view .trow[data-id="${nr.after}"]`);
  if (!row) { if (!box) SG.nr = null; return; }
  if (box && box.previousElementSibling === row) return;
  box?.remove();
  row.insertAdjacentHTML('afterend', `<div class="sgnew"><input class="sgin" value="${esc(nr.v)}" placeholder="${esc(tr('New task'))}" aria-label="${esc(tr('Title of the new task'))}" maxlength="500" autocomplete="off" enterkeyhint="done"></div>`);
  const i = document.querySelector('#view .sgnew .sgin');
  i.addEventListener('input', () => { nr.v = i.value; });
  i.addEventListener('keydown', async e => {
    e.stopPropagation();
    if (e.isComposing) return;
    if (e.key === 'Escape') { e.preventDefault(); sgNewClose(); return; }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = i.value.replace(/\s+/g, ' ').trim(); if (!v) { sgNewClose(); return; }
    nr.v = ''; i.value = '';
    try {
      const t = await createTask({title: v, list_id: nr.lid, ...(nr.sec != null ? {section_id: nr.sec} : {}), ...(nr.parent ? {parent_id: nr.parent} : {})});
      if (SG.nr === nr) { nr.after = t.id; sgNewMount(true); }
    } catch { nr.v = v; i.value = v; }
  });
  i.addEventListener('blur', () => setTimeout(() => { if (SG.nr === nr && document.activeElement !== document.querySelector('#view .sgnew .sgin') && !nr.v.trim()) sgNewClose(true); }, 200));
  if (focus || document.activeElement === document.body) i.focus();
}
function sgNewClose(quiet) {
  const nr = SG.nr; SG.nr = null;
  document.querySelector('#view .sgnew')?.remove();
  if (!quiet && nr) sgFocus({tid: nr.after, k: 'title'});
}

// the keys the active cell takes (palette.js leaves them alone): moving, Tab, Delete, Ctrl+D / A, F2 / Enter, typing
function sgCur(e) {  // the active cell that has the focus (a title only when the grid moved there)
  if (!sgOn()) return null;
  const c = sgCellOf(e.target);
  if (!c || e.target !== sgEl(c.tid, c.k)) return null;
  if (c.k === 'title' && !(SG.f && SG.f.tid === c.tid && SG.f.k === 'title')) return null;
  return c;
}
function sgOwns(e) {
  const c = !e.isComposing && sgCur(e); if (!c) return false;
  const k = e.key, mod = e.ctrlKey || e.metaKey;
  if (e.altKey) return false;
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Tab', 'Delete', 'Backspace', 'F2'].includes(k)) return !mod || k === 'Home' || k === 'End';
  if (k === 'Enter') return !mod && c.k !== 'title';
  if (mod) return /^[adAD]$/.test(k);
  return k.length === 1 && k !== ' ';
}
// ---- keyboard (window capture; palette.js leaves the keys of an active cell to this one, sgOwns)
window.addEventListener('keydown', e => {
  if (!sgOn() || e.isComposing) return;
  // Enter in a cell's field: saved by tablecells.js / listedit.js, then one row down (a new row in the last one)
  const fin = e.target.closest?.('.tcin,.ttlin');
  if (fin && e.key === 'Enter' && !e.shiftKey && !e.altKey) {
    const c = sgCellOf(fin); if (!c || !SG.f || SG.f.tid !== c.tid || SG.f.k !== c.k) return;
    if (sgMulti() && fin.classList.contains('tcin')) {  // a value typed into a range: for all its cells of the column
      e.preventDefault(); e.stopPropagation();
      const f = fieldById(+c.k.slice(2)), v = tcVal(f, fin.value), p = sgParse(taskById(c.tid), c.k, v ?? '');
      if (p.err) { toast(p.err); return; }
      fin.value = taskById(c.tid)?.fields?.[f.id] ?? ''; fin.blur();  // the field closes without a change of its own (one undo step)
      SG.moved = Date.now();
      sgSetAll(p.v, c.k).then(() => sgFocus(SG.f, true));
      return;
    }
    setTimeout(() => sgDown(c.tid, c.k), 450);
    return;
  }
  const c = sgCur(e); if (!c) return;
  if (!SG.f || SG.f.tid !== c.tid || SG.f.k !== c.k) { SG.a = SG.f = c; }
  const mod = e.ctrlKey || e.metaKey, p = sgPos(SG.f); if (!p) return;
  const keys = sgKeys(p.rows[p.r]);
  const go = (dr, dc, ext) => {
    const r = Math.max(0, Math.min(p.rows.length - 1, p.r + dr)), ci = Math.max(0, Math.min(keys.length - 1, p.c + dc));
    const k = sgKeys(p.rows[r])[ci] ?? keys[ci];
    e.preventDefault(); e.stopPropagation();
    SG.moved = Date.now();
    sgFocus({tid: +p.rows[r].dataset.id, k}, ext);
  };
  const t = taskById(c.tid);
  switch (e.key) {
    case 'ArrowUp': if (!mod && !e.altKey) go(-1, 0, e.shiftKey); return;
    case 'ArrowDown': if (!mod && !e.altKey) go(1, 0, e.shiftKey); return;
    case 'ArrowLeft': if (!mod && !e.altKey) go(0, -1, e.shiftKey); return;
    case 'ArrowRight': if (!mod && !e.altKey) go(0, 1, e.shiftKey); return;
    case 'Home': if (!e.altKey) go(mod ? -p.r : 0, -p.c, e.shiftKey); return;
    case 'End': if (!e.altKey) go(mod ? p.rows.length - 1 - p.r : 0, keys.length - 1 - p.c, e.shiftKey); return;
    case 'Tab': {
      e.preventDefault(); e.stopPropagation(); SG.moved = Date.now();
      let r = p.r, ci = p.c + (e.shiftKey ? -1 : 1);
      if (ci >= keys.length) { if (r >= p.rows.length - 1) return; r++; ci = 0; }
      if (ci < 0) { if (!r) return; r--; ci = keys.length - 1; }
      sgFocus({tid: +p.rows[r].dataset.id, k: sgKeys(p.rows[r])[ci]});
      return;
    }
    case 'Escape': if (sgMulti()) { e.preventDefault(); e.stopPropagation(); sgFocus(SG.f); } return;
    case 'Enter': case 'F2':
      if (mod || e.altKey || (c.k === 'title' && e.key === 'Enter')) return;  // Enter on a title opens the task as before (F2 / typing edit it)
      e.preventDefault(); e.stopPropagation();
      if (!sgKind(c.k) || !t || !canEdit(t)) { if (c.k === 'title' || !sgKind(c.k)) openDetail(c.tid); return; }
      sgEdit(c);
      return;
    case 'Delete': case 'Backspace':
      if (mod || e.altKey) return;
      e.preventDefault(); e.stopPropagation(); sgEmpty(); return;
  }
  if (mod && !e.altKey && (e.key === 'd' || e.key === 'D')) { e.preventDefault(); e.stopPropagation(); sgFillDown(); return; }
  if (mod && !e.altKey && (e.key === 'a' || e.key === 'A')) {  // the whole column
    e.preventDefault(); e.stopPropagation();
    SG.a = {tid: +p.rows[0].dataset.id, k: c.k}; SG.f = {tid: +p.rows[p.rows.length - 1].dataset.id, k: c.k}; sgPaint(); sgEl(SG.f.tid, SG.f.k)?.focus({preventScroll: true});
    return;
  }
  // typing overwrites (text, number, link, title); a choice / date / person opens its picker
  if (!mod && !e.altKey && e.key.length === 1 && e.key !== ' ' && t && canEdit(t) && sgKind(c.k)) {
    const f = c.k.startsWith('f:') ? fieldById(+c.k.slice(2)) : null;
    e.preventDefault(); e.stopPropagation();
    if (c.k === 'title' || (f && TC_INPUT.includes(f.type))) sgEdit(c, e.key); else sgEdit(c);
  }
}, true);
// Space on a cell that is not a field: the list's own key (select / open) stays; on a field cell tablecells.js edits it

// ---- the mouse: a click activates the cell (a field cell is edited at once as before), Shift+click / dragging select a
// range; a click on the due date / the assignee cell opens their picker
window.addEventListener('pointerdown', e => {
  if (!sgOn() || e.button !== 0 || e.pointerType === 'touch') return;
  const c = sgCellOf(e.target); if (!c) { return; }
  if (e.target.closest('[data-sgfill]')) { sgFillDrag(e); return; }
  if (c.k === 'title' && !e.shiftKey) return;  // the title opens the task as before
  if (e.shiftKey && SG.a) { e.preventDefault(); SG.f = c; SG.click = Date.now(); sgPaint(); sgEl(c.tid, c.k)?.focus({preventScroll: true}); return; }
  SG.a = SG.f = c; SG.drag = {x: e.clientX, y: e.clientY, on: false};
  const mv = ev => {
    const d = SG.drag; if (!d) return;
    if (!d.on && Math.abs(ev.clientX - d.x) + Math.abs(ev.clientY - d.y) < 8) return;
    d.on = true;
    const o = sgCellOf(document.elementFromPoint(ev.clientX, ev.clientY));
    if (o && (o.tid !== SG.f.tid || o.k !== SG.f.k) && o.k !== 'title') { SG.f = o; sgPaint(); }
  };
  const up = () => {
    document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up);
    if (SG.drag?.on) { SG.click = Date.now(); window.getSelection?.()?.removeAllRanges?.(); sgEl(SG.f.tid, SG.f.k)?.focus({preventScroll: true}); }
    SG.drag = null; sgPaint();
  };
  document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
}, true);
window.addEventListener('click', e => {
  if (!sgOn()) return;
  const c = sgCellOf(e.target); if (!c) return;
  // the click that ends a range (Shift+click, dragging) does not edit or open anything
  if (SG.click && Date.now() - SG.click < 400) { SG.click = 0; e.preventDefault(); e.stopPropagation(); return; }
  if ((c.k === 'due' || c.k === 'who') && !e.target.closest('a[href],button')) {
    const t = taskById(c.tid); if (!t || !canEdit(t)) return;
    e.preventDefault(); e.stopPropagation();
    sgFocus(c); sgEdit(c);
  } else if (c.k !== 'title') { SG.a = SG.f = c; sgPaint(); }
}, true);

// a drag that starts in a cell selects cells; it does not pick up the row (the title and the handle still move it)
window.addEventListener('dragstart', e => { if (SG.drag && sgCellOf(e.target?.nodeType === 1 ? document.elementFromPoint(SG.drag.x, SG.drag.y) : null)) e.preventDefault(); }, true);

// ---- fill down: the first row's values of the range into the rows below (Ctrl/Cmd+D, the handle at the cell's corner)
function sgFillDown() {
  const rg = sgRange(); if (!rg.length) return;
  const top = Math.min(...rg.map(c => c.r)), first = {};
  for (const c of rg) if (c.r === top) first[c.k] = taskById(c.tid);
  const chg = rg.filter(c => c.r !== top && sgKind(c.k) && c.k !== 'title').map(c => ({tid: c.tid, k: c.k, v: sgGet(first[c.k], c.k)}));
  if (!chg.length) { toast(tr('Select the cells below too (Shift+↓), then fill down')); return; }
  sgWrite(chg, trn('{0} cell filled down', '{0} cells filled down', chg.length));
}
function sgFillDrag(e) {
  e.preventDefault(); e.stopPropagation();
  const from = SG.f; SG.a = from;
  const mv = ev => { const o = sgCellOf(document.elementFromPoint(ev.clientX, ev.clientY)); if (o) { const p = sgPos(o); if (p) { SG.f = {tid: o.tid, k: from.k}; sgPaint(); } } };
  const up = () => {
    document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up);
    SG.click = Date.now();
    const p = sgPos(SG.f), q = sgPos(from);
    if (p && q && p.r > q.r) sgFillDown();
    else { SG.f = from; sgPaint(); }
  };
  document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
}

// ---- copy: the range as a table (TSV for Sheets / Excel, HTML for documents); read-only lists too
function sgCopyData() {  // {text, html, n} of the range (null = no active cell)
  const rg = SG.f ? sgRange() : []; if (!rg.length) return null;
  const rows = [...new Set(rg.map(c => c.r))].sort((a, b) => a - b);
  const grid = rows.map(r => rg.filter(c => c.r === r).sort((a, b) => a.c - b.c).map(c => sgText(taskById(c.tid) || {}, c.k)));
  const tsvCell = s => /[\t\n"]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  return {text: grid.map(r => r.map(tsvCell).join('\t')).join('\n'), html: `<table>${grid.map(r => `<tr>${r.map(s => `<td>${esc(s)}</td>`).join('')}</tr>`).join('')}</table>`, n: rg.length};
}
document.addEventListener('copy', e => {
  if (!sgOn() || !SG.f || !sgCellOf(document.activeElement) || window.getSelection?.()?.toString() || !e.clipboardData) return;
  const d = sgCopyData(); if (!d) return;
  e.clipboardData.setData('text/plain', d.text);
  e.clipboardData.setData('text/html', d.html);
  e.preventDefault();
  toast(trn('{0} cell copied', '{0} cells copied', d.n));
});
// ---- paste: tab-separated cells from Sheets / Excel -> a preview (columns mapped to the fields, wrong values marked)
function sgTsv(s) {  // rows of cells; quoted cells may hold tabs, line breaks and "" (Excel / Sheets)
  const rows = [[]]; let cur = '', q = false;
  s = s.replace(/\r\n?/g, '\n').replace(/\n$/, '');
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (q) { if (ch === '"' && s[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; continue; }
    if (ch === '"' && cur === '') { q = true; continue; }
    if (ch === '\t') { rows[rows.length - 1].push(cur); cur = ''; } else if (ch === '\n') { rows[rows.length - 1].push(cur); cur = ''; rows.push([]); } else cur += ch;
  }
  rows[rows.length - 1].push(cur);
  return rows;
}
document.addEventListener('paste', e => {
  if (!sgOn() || !SG.f) return;
  const c = sgCellOf(document.activeElement); if (!c || document.activeElement !== sgEl(c.tid, c.k)) return;
  const txt = e.clipboardData?.getData('text/plain') || ''; if (!txt) return;
  e.preventDefault();
  sgPaste(txt);
});
function sgPaste(txt) {  // pasted text at the active cell -> the preview
  const t = SG.f && taskById(SG.f.tid); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  sgPasteModal(sgTsv(txt));
}
function sgPasteModal(data) {
  const p = sgPos(SG.f); if (!p || !data.length) return;
  const t0 = taskById(SG.f.tid), l = listById(t0.list_id), keys = sgKeys(p.rows[p.r]);
  const can = keys.filter(k => SG_PASTE.includes(k) || sgKind(k) === 'f');
  const width = Math.max(...data.map(r => r.length));
  if (data.length * width > 5000) { toast(tr('At most 5000 cells at once')); return; }
  // the first row are column titles when it names the columns: mapped by name, not pasted
  const byName = s => can.find(k => sgColName(l, k).toLowerCase() === String(s).trim().toLowerCase());
  const st = {head: data.length > 1 && data[0].filter(byName).length >= Math.max(1, Math.ceil(width / 2)), map: []};
  const remap = () => {
    if (st.head) st.map = Array.from({length: width}, (_, i) => byName(data[0][i] || '') || '');
    else { const i0 = keys.indexOf(SG.f.k); st.map = Array.from({length: width}, (_, i) => { const k = keys[i0 + i]; return k && can.includes(k) ? k : ''; }); }
  };
  remap();
  const plan = () => {  // [{tid | null (new), cells: [{k, raw, v, err}]}]
    const rows = st.head ? data.slice(1) : data, out = [];
    rows.forEach((r, i) => {
      const row = p.rows[p.r + i], t = row ? taskById(+row.dataset.id) : null;
      const cells = st.map.map((k, j) => { if (!k) return null; const x = sgParse(t || {list_id: l.id}, k, r[j] ?? ''); return {k, raw: r[j] ?? '', ...x}; });
      out.push({tid: t?.id || null, t, cells});
    });
    for (const r of out) if (!r.tid) {  // a new task needs a title
      const tc = r.cells.find(x => x?.k === 'title');
      if (!tc) r.err = tr('A new task needs a title column');
    }
    return out;
  };
  const md = modal(`<h3>${ic('clipboard', 's')}${tr('Paste cells')}</h3><div class="sgpv"></div>
    <div class="foot"><span class="muted sgpn"></span><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Apply')}</button></div>`);
  md.classList.add('sgpmd');
  const draw = () => {
    const pl = plan(), bad = pl.reduce((n, r) => n + r.cells.filter(x => x?.err).length + (r.err ? 1 : 0), 0), nw = pl.filter(r => !r.tid && !r.err).length;
    const sel = j => `<select data-sgmap="${j}" aria-label="${esc(tr('Column {0}', j + 1))}"><option value="">${esc(tr('skip'))}</option>${can.map(k => `<option value="${esc(k)}" ${st.map[j] === k ? 'selected' : ''}>${esc(sgColName(l, k))}</option>`).join('')}</select>`;
    $('.sgpv', md).innerHTML = `<label class="chkl"><input type="checkbox" data-sghead ${st.head ? 'checked' : ''}> ${esc(tr('The first row holds column titles'))}</label>
      <div class="sgpt"><table><thead><tr><th></th>${st.map.map((_, j) => `<th>${sel(j)}</th>`).join('')}</tr></thead><tbody>${pl.slice(0, 50).map(r => `<tr class="${r.err ? 'sgbad' : ''}"><th title="${esc(r.err || '')}">${r.tid ? esc(mdPlain(r.t.title).slice(0, 30)) : `<b>${esc(tr('new'))}</b>`}</th>${r.cells.map(x => !x ? '<td class="muted">–</td>' : `<td class="${x.err ? 'sgbad' : ''}" title="${esc(x.err || '')}">${esc(String(x.raw).slice(0, 60))}${x.err ? `<span class="sr"> (${esc(x.err)})</span>` : ''}</td>`).join('')}</tr>`).join('')}</tbody></table>${pl.length > 50 ? `<p class="muted">${esc(tr('and {0} more rows', pl.length - 50))}</p>` : ''}</div>`;
    $('.sgpn', md).textContent = [trn('{0} task changes', '{0} tasks change', pl.filter(r => r.tid).length), nw ? trn('{0} new task', '{0} new tasks', nw) : '', bad ? trn('{0} invalid cell is skipped', '{0} invalid cells are skipped', bad) : ''].filter(Boolean).join(' · ');
  };
  draw();
  md.addEventListener('change', e => {
    if (e.target.dataset.sghead !== undefined) { st.head = e.target.checked; remap(); draw(); return; }
    const j = e.target.dataset.sgmap; if (j !== undefined) { st.map[+j] = e.target.value; draw(); }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'ok') return;
    b.disabled = true;
    const pl = plan(), chg = [], add = [];
    for (const r of pl) {
      const ok = r.cells.filter(x => x && !x.err);
      if (r.tid) for (const x of ok) chg.push({tid: r.tid, k: x.k, v: x.v});
      else if (!r.err && ok.some(x => x.k === 'title')) add.push(ok);
    }
    if (add.length > 200) { toast(tr('At most 200 new tasks at once')); b.disabled = false; return; }
    md.remove();
    await sgPasteApply(l, t0, chg, add);
  });
}
async function sgPasteApply(l, t0, chg, add) {
  const n = chg.length;
  await histGroup(async () => {
    if (n) await sgWrite(chg);
    for (const cells of add) {
      const body = {list_id: l.id, ...(t0.section_id != null ? {section_id: t0.section_id} : {}), ...(t0.parent_id ? {parent_id: t0.parent_id} : {})};
      for (const x of cells) {
        if (x.v == null) continue;
        if (x.k === 'title') body.title = x.v; else if (x.k === 'due') body.due = x.v; else if (x.k === 'who') body.assignee_id = x.v; else (body.fields || (body.fields = {}))[x.k.slice(2)] = x.v;
      }
      try { await createTask(body); } catch { break; }
    }
  }, tr('Cells pasted'));
  HIST.gToast = null;
  const e = HIST.undo[HIST.undo.length - 1];
  if (e) histToast([n ? trn('{0} cell pasted', '{0} cells pasted', n) : '', add.length ? trn('{0} new task', '{0} new tasks', add.length) : ''].filter(Boolean).join(' · '), e);
  await load(); render();
}

// ---- filter by a column (the arrow in the column title): only the tasks with one value of a choice, checkbox, person or
// the assignee; for this list until "Show all" (this device, this session). The sum row follows (it counts the shown tasks).
SG.cf = {};  // list id -> {k, v}
function sgKeep(t, rk = S.route.key) {
  const f = rk.startsWith('l:') ? SG.cf[+rk.slice(2)] : null;
  if (!f || t.list_id !== +rk.slice(2)) return true;
  const v = sgGet(t, f.k);
  return f.v == null ? v == null || v === '' : String(v ?? '') === String(f.v);
}
function sgColVals(l, k) {  // [[value, label]] a column can be filtered by (null = empty)
  if (k === 'who') return [...listPeople(l).map(p => [p.user_id, p.name]), [null, tr('Nobody')]];
  const f = k.startsWith('f:') ? fieldById(+k.slice(2)) : null; if (!f) return [];
  if (f.type === 'select') return [...(f.options?.options || []).map(o => [o.id, o.name]), [null, tr('empty')]];
  if (f.type === 'checkbox') return [['1', tr('ticked')], [null, tr('not ticked')]];
  if (f.type === 'person') return [...listPeople(l).map(p => [String(p.user_id), p.name]), [null, tr('empty')]];
  return [];
}
function sgColMenu(l, k, anchor) {
  const vs = sgColVals(l, k), cur = SG.cf[l.id];
  const out = [];
  if (vs.length) out.push({label: tr('Filter by this column…'), icon: 'filter', fn: () => setTimeout(() => menu(anchor, [{label: tr('Show only'), dis: true, cls: 'mhead'}, '-',
    ...vs.map(([v, n]) => ({label: n, on: cur?.k === k && cur.v === v, fn: () => { SG.cf[l.id] = {k, v}; render(); }}))]), 0)});
  if (cur) out.push({label: tr('Show all'), icon: 'x', fn: () => { delete SG.cf[l.id]; render(); }});
  return out.length ? ['-', ...out] : [];
}
function sgFilterNote(l) {
  const f = l && SG.cf[l.id]; if (!f) return '';
  const n = (sgColVals(l, f.k).find(x => x[0] === f.v) || [0, '?'])[1];
  return `<div class="favnote muted sgfnote">${ic('filter', 's')}<span>${esc(tr('Only {0}: {1}', sgColName(l, f.k), n))}</span><button type="button" class="linkbtn" data-sgfoff="${l.id}">${esc(tr('Show all'))}</button></div>`;
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-sgfoff]'); if (b) { delete SG.cf[+b.dataset.sgfoff]; render(); } });
