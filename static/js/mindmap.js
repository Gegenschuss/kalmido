/* Kalmido web client: the mind map (#1201) -- a view of a list next to List / Kanban / Timeline. The list's name in the
   middle, its sections and tasks as branches, subtasks as sub-branches (as deep as subtasks go). Every branch IS a task:
   the app's own routes create, rename, move and delete it, each action one Undo step, and only where the list lets me
   write (view-only lists show the map without changes). Typing like Mindjet: Enter = new branch next to it, Tab = sub-
   branch, Shift+Tab = one level up, Delete = delete, Space = fold, arrows move the selection, F2 / double click = rename;
   dragging a branch onto another hangs it there (subtask / other section). Phones: drag the map with a finger, pinch to
   zoom, a tap selects, a second tap opens the actions in a sheet; the outline (an indented list) is the other way to look
   at it. Export: Markdown outline, SVG, PNG (drawn by the browser, no library); import: Markdown list, OPML, FreeMind .mm
   (parsed by the server, which refuses DOCTYPE / entities) as tasks under the selected branch.
   A ```mindmap block in a knowledge page (wiki.js) draws its Markdown list the same way (display only).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

P.mindmap = icPath('M7 10H9.5M9.5 10C11.5 10 11.5 5 14 5H17M9.5 10C11.5 10 11.5 15 14 15H17') + icDot(4.5, 10);
const MM = {lid: null, sel: 'r', fold: new Set(), pan: null, edit: null, outline: false, drag: null, ptr: new Map(), pinch: null, last: null};
const MM_H = 34, MM_GAP = 10, MM_COL = 56, MM_PADX = 12, MM_MAXW = 240, MM_FONT = '14px system-ui, -apple-system, "Segoe UI", sans-serif';
let mm_ctx = null;
function mm_textW(s, font = MM_FONT) {
  if (!mm_ctx) { try { mm_ctx = document.createElement('canvas').getContext('2d'); } catch { mm_ctx = null; } }
  if (!mm_ctx) return String(s).length * 7.5;
  mm_ctx.font = font; return mm_ctx.measureText(String(s)).width;
}
function mm_clip(s, w) {  // the title shortened to w pixels (with …)
  s = String(s || ''); if (mm_textW(s) <= w) return s;
  let lo = 0, hi = s.length;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (mm_textW(s.slice(0, m) + '…') <= w) lo = m; else hi = m - 1; }
  return s.slice(0, lo) + '…';
}
// ---- the tree of a list: {id, kind: root | sec | task, title, t?, kids}
function mm_listTree(l) {
  const all = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.deleted_at);
  const kidsOf = id => sortTasks(all.filter(t => t.parent_id === id));
  const node = t => ({id: 't' + t.id, kind: 'task', title: t.title, t, kids: kidsOf(t.id).map(node)});
  const top = all.filter(t => !t.parent_id), secs = S.sections.filter(s => s.list_id === l.id);
  const root = {id: 'r', kind: 'root', title: lname(l), kids: sortTasks(top.filter(t => !t.section_id || !secs.some(s => s.id === t.section_id))).map(node)};
  for (const s of secs) root.kids.push({id: 's' + s.id, kind: 'sec', title: s.name, sec: s, kids: sortTasks(top.filter(t => t.section_id === s.id)).map(node)});
  return root;
}
// a Markdown list (``` mindmap block) -> the same tree shape (display only)
function mm_mdTree(text, title = '') {
  const root = {id: 'r', kind: 'root', title, kids: []}, stack = [];
  let n = 0;
  for (const ln of String(text).split('\n')) {
    const m = /^(\s*)(?:[-*+•]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.*)$/.exec(ln); if (!m || !m[2].trim()) continue;
    const ind = m[1].replace(/\t/g, '    ').length, nd = {id: 'm' + n++, kind: 'task', title: m[2].trim(), kids: []};
    while (stack.length && stack[stack.length - 1][0] >= ind) stack.pop();
    (stack.length ? stack[stack.length - 1][1].kids : root.kids).push(nd); stack.push([ind, nd]);
  }
  if (!root.title && root.kids.length === 1) return {...root.kids[0], id: 'r', kind: 'root'};
  return root;
}
// ---- layout: left to right; a leaf takes one row, a parent sits in the middle of its children
function mm_layout(root, fold) {
  const nodes = [], cols = [];
  const walk = (n, d, parent) => {
    const label = n.kind === 'root' ? n.title : n.title;
    n.w = Math.min(MM_MAXW, Math.max(n.kind === 'root' ? 80 : 40, mm_textW(label, n.kind === 'root' ? 'bold ' + MM_FONT : MM_FONT) + 2 * MM_PADX + (n.t && mm_meta(n.t) ? mm_textW(mm_meta(n.t), '11px system-ui') + 8 : 0)));
    n.d = d; n.parent = parent; n.open = !fold.has(n.id) || n.kind === 'root';
    cols[d] = Math.max(cols[d] || 0, n.w); nodes.push(n);
    if (n.open) n.kids.forEach(k => walk(k, d + 1, n));
  };
  walk(root, 0, null);
  const xs = [0]; for (let d = 1; d < cols.length; d++) xs[d] = xs[d - 1] + cols[d - 1] + MM_COL;
  let y = 0;
  const place = n => {
    n.x = xs[n.d];
    const ks = n.open ? n.kids : [];
    if (!ks.length) { n.y = y; y += MM_H + MM_GAP; return; }
    ks.forEach(place);
    n.y = (ks[0].y + ks[ks.length - 1].y) / 2;
  };
  place(root);
  return {nodes, w: xs[cols.length - 1] + cols[cols.length - 1], h: Math.max(MM_H, y - MM_GAP)};
}
function mm_meta(t) {
  if (!t || !t.list_id) return '';
  const who = t.assignee_id ? personName(t.list_id, t.assignee_id) : '';
  return [t.due ? fmtDateLoc(t.due) : '', who ? who.split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase() : ''].filter(Boolean).join(' · ');
}
// the SVG of a laid-out tree (also the export: o.inline = colours written into the elements)
function mm_svg(L, o = {}) {
  const pad = 16, col = o.colors || {}, a = col.accent, st = (k, v) => o.inline ? ` ${k}="${v}"` : '';
  const lines = L.nodes.filter(n => n.parent).map(n => {
    const p = n.parent, x1 = p.x + p.w, y1 = p.y + MM_H / 2, x2 = n.x, y2 = n.y + MM_H / 2, dx = (x2 - x1) / 2;
    return `<path class="mmline ${n.t && n.t.status ? 'done' : ''}" d="M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}"${st('fill', 'none')}${st('stroke', a)}${st('stroke-width', '1.6')}${st('opacity', n.t && n.t.status ? '.35' : '.7')}/>`;
  }).join('');
  const box = L.nodes.map(n => {
    const done = !!(n.t && n.t.status), sel = !o.inline && MM.sel === n.id && o.live, meta = n.t ? mm_meta(n.t) : '', mw = meta ? mm_textW(meta, '11px system-ui') + 8 : 0;
    const title = mm_clip(n.title, n.w - 2 * MM_PADX - mw), cls = `mmnode ${n.kind} ${done ? 'done' : ''} ${sel ? 'sel' : ''} ${MM.drag?.over === n.id ? 'drop' : ''}`;
    const nk = n.kids.length && !n.open ? `<g class="mmfold"><circle cx="${n.w + 9}" cy="${MM_H / 2}" r="8"${st('fill', a)}/><text x="${n.w + 9}" y="${MM_H / 2 + 4}" text-anchor="middle"${st('fill', '#fff')}${st('font-size', '10')}>${n.kids.length > 99 ? '99' : n.kids.length}</text></g>` : '';
    return `<g class="${cls}" id="${o.live ? 'mm-n-' + n.id : ''}" data-mmn="${n.id}" transform="translate(${n.x} ${n.y})" ${o.live ? `role="treeitem" aria-level="${n.d + 1}" aria-selected="${sel}" ${n.kids.length ? `aria-expanded="${n.open}"` : ''} aria-label="${esc(n.title)}"` : ''}${st('opacity', done ? '.5' : '1')}>
      <rect width="${n.w}" height="${MM_H}" rx="${n.kind === 'root' ? MM_H / 2 : 9}"${st('fill', n.kind === 'root' ? a : col.bg)}${st('stroke', n.kind === 'root' ? a : col.line)}/>
      <text x="${MM_PADX}" y="${MM_H / 2 + 5}" class="mmt"${st('fill', n.kind === 'root' ? '#fff' : col.fg)}${st('font', (n.kind === 'root' || n.kind === 'sec' ? 'bold ' : '') + MM_FONT)}${done && o.inline ? st('text-decoration', 'line-through') : ''}>${esc(title)}</text>
      ${meta ? `<text x="${n.w - MM_PADX}" y="${MM_H / 2 + 4}" text-anchor="end" class="mmm"${st('fill', col.mut)}${st('font-size', '11')}>${esc(meta)}</text>` : ''}${nk}</g>`;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" class="mmsvg" width="${L.w + 2 * pad + 20}" height="${L.h + 2 * pad}" viewBox="${-pad} ${-pad} ${L.w + 2 * pad + 20} ${L.h + 2 * pad}"${o.live ? ' aria-hidden="false"' : ' role="img"'}>${lines}${box}</svg>`;
}
// ---- the view of a list
function mm_state(l) {
  if (MM.lid !== l.id) {
    MM.lid = l.id; MM.sel = 'r'; MM.edit = null; MM.pan = null;
    MM.fold = new Set((LS.get('mmFold', {}) || {})[l.id] || []);
    MM.outline = !!(LS.get('mmOutline', {}) || {})[l.id];
  }
}
function mm_foldSave() { const o = LS.get('mmFold', {}) || {}; o[MM.lid] = [...MM.fold].slice(0, 500); LS.set('mmFold', o); }
const mm_ro = l => !canEditList(l.id);
function viewMindmap(l) {
  mm_state(l);
  const tree = mm_listTree(l), L = mm_layout(tree, MM.fold); MM.last = {tree, L};
  if (!L.nodes.some(n => n.id === MM.sel)) MM.sel = 'r';
  const ro = mm_ro(l);
  const bar = `<div class="mmbar" role="toolbar" aria-label="${esc(tr('Mind map'))}">
    ${ro ? `<span class="muted">${tr('View only')}</span>` : `<button type="button" class="btn sm" data-mm="sib" title="${esc(tr('New branch (Enter)'))}">${ic('plus', 's')}<span>${tr('Branch')}</span></button>
    <button type="button" class="btn sm" data-mm="kid" title="${esc(tr('New sub-branch (Tab)'))}">${ic('indent', 's')}<span>${tr('Sub-branch')}</span></button>`}
    <span class="spacer"></span>
    <div class="seg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-mm="as-map" class="${MM.outline ? '' : 'on'}" aria-pressed="${!MM.outline}">${ic('mindmap', 's')}<span class="sr">${tr('Mind map')}</span></button><button type="button" data-mm="as-outline" class="${MM.outline ? 'on' : ''}" aria-pressed="${MM.outline}" title="${esc(tr('Outline'))}">${ic('list', 's')}<span class="sr">${tr('Outline')}</span></button></div>
    ${MM.outline ? '' : `<button type="button" class="iconbtn" data-mm="fit" title="${esc(tr('Fit to screen'))}" aria-label="${esc(tr('Fit to screen'))}">${ic('expand', 's')}</button>`}
    <button type="button" class="iconbtn" data-mm="more" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  if (MM.outline) return `<div class="mmwrap mmout" data-lid="${l.id}">${bar}${mm_outlineHtml(tree, ro)}</div>`;
  if (!MM.pan) MM.pan = mm_fitPan(L);
  setTimeout(mm_bind, 0);
  return `<div class="mmwrap" data-lid="${l.id}">${bar}<div class="mmstage" tabindex="0" role="tree" aria-label="${esc(tr('Mind map of {0}', lname(l)))}" aria-activedescendant="mm-n-${MM.sel}">
    <div class="mmcanvas" style="transform:translate(${MM.pan.x}px,${MM.pan.y}px) scale(${MM.pan.k})">${mm_svg(L, {live: true})}</div>
    ${MM.edit ? mm_editHtml(L) : ''}</div>
    <p class="mmhint muted">${isTouch() ? tr('Tap a branch to select it, tap again for its actions, hold it to rehang it. Drag the map with one finger, zoom with two.') : tr('Enter: branch · Tab: sub-branch · Shift+Tab: up a level · Del: delete · Space: fold · F2: rename · drag to rehang')}</p></div>`;
}
function mm_fitPan(L, box) {
  const w = box?.clientWidth || Math.min(innerWidth, 1100), h = box?.clientHeight || Math.max(260, innerHeight - 260);
  const k = Math.max(0.35, Math.min(1, (w - 24) / (L.w + 60), (h - 24) / (L.h + 40)));
  return {x: 16 + 16 * k, y: Math.max(16, (h - L.h * k) / 2), k};
}
function mm_outlineHtml(tree, ro) {
  const li = n => `<li><div class="mmoi ${n.t && n.t.status ? 'done' : ''} ${MM.sel === n.id ? 'sel' : ''}" data-mmn="${n.id}">${n.kids.length ? `<button type="button" class="iconbtn mmtog" data-mm="fold" data-n="${n.id}" aria-expanded="${!MM.fold.has(n.id)}" aria-label="${esc(MM.fold.has(n.id) ? tr('Unfold') : tr('Fold'))}">${ic(MM.fold.has(n.id) ? 'right' : 'chev', 's')}</button>` : '<span class="mmtog"></span>'}
    <span class="mmot">${esc(n.title)}</span>${n.t && mm_meta(n.t) ? `<small class="muted">${esc(mm_meta(n.t))}</small>` : ''}</div>${n.kids.length && !MM.fold.has(n.id) ? `<ul>${n.kids.map(li).join('')}</ul>` : ''}</li>`;
  return `<ul class="mmoutline" role="tree">${li(tree)}</ul>`;
}
function mm_editHtml(L) {
  const e = MM.edit, n = L.nodes.find(x => x.id === e.at); if (!n) return '';
  const k = MM.pan.k, x = e.mode === 'rename' ? n.x : n.x + (e.mode === 'kid' ? n.w + MM_COL : 0), y = e.mode === 'rename' ? n.y : n.y + (e.mode === 'sib' ? MM_H + MM_GAP : 0);
  return `<input class="mmedit" id="mm-edit" value="${esc(e.value || '')}" aria-label="${esc(e.mode === 'rename' ? tr('Rename') : tr('New branch'))}" maxlength="500" autocomplete="off" style="left:${MM.pan.x + (x + 16) * k}px;top:${MM.pan.y + (y + 16) * k}px;width:${Math.max(160, (e.mode === 'rename' ? n.w : 200) * k)}px;height:${MM_H * k}px;font-size:${Math.max(12, 14 * k)}px">`;
}
const mm_node = id => MM.last?.L.nodes.find(n => n.id === id) || null;
function mm_draw() {
  const st = $('.mmstage'); if (!st) return;
  renderView();
  setTimeout(() => { const s2 = $('.mmstage'); if (MM.edit) { const i = $('#mm-edit'); if (i) { i.focus(); i.select(); } } else if (s2 && document.activeElement !== s2 && !isTouch()) s2.focus({preventScroll: true}); }, 0);
}
function mm_select(id) {
  MM.sel = id;
  const st = $('.mmstage'); if (!st) { renderView(); return; }
  $$('.mmnode.sel', st).forEach(g => { g.classList.remove('sel'); g.setAttribute('aria-selected', 'false'); });
  const g = $(`[data-mmn="${id}"]`, st); if (g) { g.classList.add('sel'); g.setAttribute('aria-selected', 'true'); }
  st.setAttribute('aria-activedescendant', 'mm-n-' + id);
  mm_inView(id);
}
function mm_inView(id) {  // the selected branch scrolled into the stage
  const st = $('.mmstage'), n = mm_node(id); if (!st || !n || !MM.pan) return;
  const k = MM.pan.k, x = MM.pan.x + (n.x + 16) * k, y = MM.pan.y + (n.y + 16) * k, w = n.w * k, h = MM_H * k;
  let dx = 0, dy = 0;
  if (x < 8) dx = 8 - x; else if (x + w > st.clientWidth - 8) dx = st.clientWidth - 8 - x - w;
  if (y < 8) dy = 8 - y; else if (y + h > st.clientHeight - 8) dy = st.clientHeight - 8 - y - h;
  if (dx || dy) { MM.pan.x += dx; MM.pan.y += dy; mm_applyPan(); }
}
function mm_applyPan() { const c = $('.mmcanvas'); if (c) c.style.transform = `translate(${MM.pan.x}px,${MM.pan.y}px) scale(${MM.pan.k})`; const i = $('#mm-edit'); if (i) { i.remove(); MM.edit = null; } }
// ---- actions (the app's own task routes: one Undo step each)
function mm_target(n, mode) {  // where a new branch goes: {parent_id} | {section_id} | {} (top level)
  if (!n) return null;
  if (mode === 'kid') return n.kind === 'task' ? {parent_id: n.t.id} : n.kind === 'sec' ? {section_id: n.sec.id} : {};
  if (n.kind === 'root') return {};
  if (n.kind === 'sec') return {section_id: n.sec.id};
  return n.t.parent_id ? {parent_id: n.t.parent_id} : n.t.section_id ? {section_id: n.t.section_id} : {};
}
function mm_startNew(mode) {
  const l = listById(MM.lid); if (!l || mm_ro(l)) return;
  const n = mm_node(MM.sel) || mm_node('r');
  MM.edit = {mode: n.kind === 'root' || n.kind === 'sec' ? 'kid' : mode, at: n.id, value: ''};
  if (MM.outline) { mm_ask(); return; }
  mm_draw();
}
async function mm_ask() {  // the outline has no editor in place: a small dialog
  const e = MM.edit, v = await askPrompt(e.mode === 'rename' ? tr('Rename') : e.mode === 'kid' ? tr('New sub-branch') : tr('New branch'), e.value || '', {input: {max: 500}});
  if (v == null) { MM.edit = null; return; }
  mm_commit(v);
}
function mm_rename(n) { MM.edit = {mode: 'rename', at: n.id, value: n.t.title}; if (MM.outline) mm_ask(); else mm_draw(); }
function mm_sortAfter(n) {  // a sort value right after n among its siblings (manual order), else nothing
  if (!n || n.kind !== 'task' || typeof n.t.sort !== 'number') return {};
  const sib = n.parent?.kids || [], i = sib.indexOf(n), nx = sib[i + 1]?.t;
  return {sort: nx && typeof nx.sort === 'number' && nx.sort > n.t.sort ? (n.t.sort + nx.sort) / 2 : n.t.sort + 1};
}
async function mm_commit(value) {
  const e = MM.edit; MM.edit = null;
  const v = String(value || '').trim(), n = mm_node(e?.at), l = listById(MM.lid);
  if (!e || !n || !l) { mm_draw(); return; }
  if (e.mode === 'rename') {
    if (v && n.kind === 'task' && v !== n.t.title) { try { await patchTask(n.t.id, {title: v}); } catch { /* the server said why */ } }
    mm_draw(); return;
  }
  if (!v) { mm_draw(); return; }
  const tg = mm_target(n, e.mode);
  if (tg.parent_id) { MM.fold.delete('t' + tg.parent_id); mm_foldSave(); }
  if (tg.section_id && e.mode === 'kid') { MM.fold.delete('s' + tg.section_id); mm_foldSave(); }
  try {
    const t = await createTask({title: v, list_id: l.id, ...tg, ...(e.mode === 'sib' ? mm_sortAfter(n) : {})});
    MM.sel = 't' + t.id;
  } catch { /* shown */ }
  mm_draw();
}
async function mm_outdent() {
  const n = mm_node(MM.sel); if (!n || n.kind !== 'task' || mm_ro(listById(MM.lid))) return;
  const t = n.t;
  if (t.parent_id) { const p = taskById(t.parent_id); await patchTask(t.id, p?.parent_id ? {parent_id: p.parent_id} : {parent_id: null, section_id: p?.section_id || null}).catch(() => {}); }
  else if (t.section_id) await patchTask(t.id, {section_id: null}).catch(() => {});
  mm_draw();
}
async function mm_delete() {
  const n = mm_node(MM.sel); if (!n || n.kind !== 'task' || mm_ro(listById(MM.lid))) return;
  const sib = n.parent?.kids || [], i = sib.indexOf(n);
  MM.sel = (sib[i + 1] || sib[i - 1] || n.parent)?.id || 'r';
  await deleteTask(n.t.id).catch(() => {});
  mm_draw();
}
function mm_toggle(id) {
  const n = mm_node(id) || mm_listFind(id); if (!n || !n.kids?.length || id === 'r') return;
  if (MM.fold.has(id)) MM.fold.delete(id); else MM.fold.add(id);
  mm_foldSave(); mm_draw();
}
const mm_listFind = id => { const f = n => n.id === id ? n : n.kids.map(f).find(Boolean) || null; return MM.last ? f(MM.last.tree) : null; };
function mm_move(key) {
  const n = mm_node(MM.sel); if (!n) return;
  let to = null;
  if (key === 'ArrowLeft') to = n.parent;
  else if (key === 'ArrowRight') { if (n.kids.length && !n.open) { mm_toggle(n.id); return; } to = n.open ? n.kids[Math.floor((n.kids.length - 1) / 2)] : null; }
  else {  // up / down: the next branch above / below in the same column, else the nearest one
    const col = MM.last.L.nodes.filter(x => x.d === n.d && (key === 'ArrowUp' ? x.y < n.y : x.y > n.y));
    to = col.sort((a, b) => key === 'ArrowUp' ? b.y - a.y : a.y - b.y)[0] || null;
  }
  if (to) mm_select(to.id);
}
async function mm_rehang(id, onto) {  // drag and drop: id hangs at onto (a task: its subtask; a section; the root: top level)
  const n = mm_listFind(id), o = mm_listFind(onto); if (!n || !o || n.kind !== 'task' || id === onto) return;
  const under = x => { for (let p = x; p; p = p.parent) if (p.id === id) return true; return false; };
  const on = mm_node(onto); if (on && under(on)) { toast(tr('A task cannot be nested under itself')); return; }
  const body = o.kind === 'task' ? {parent_id: o.t.id} : o.kind === 'sec' ? {parent_id: null, section_id: o.sec.id} : {parent_id: null, section_id: null};
  if (o.kind === 'task') { MM.fold.delete(o.id); mm_foldSave(); }
  await patchTask(n.t.id, body).catch(() => {});
  MM.sel = id; mm_draw();
}
// ---- export / import
function mm_md(n, d = 0) { return (d ? '  '.repeat(d - 1) + '- ' : '# ') + n.title.replace(/\n/g, ' ') + '\n' + n.kids.map(k => mm_md(k, d + 1)).join(''); }
function mm_download(name, blob) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }
function mm_exportSvg() {
  const cs = getComputedStyle(document.body), v = k => cs.getPropertyValue(k).trim();
  const colors = {accent: v('--accent') || '#7c5cff', bg: v('--bg') || '#ffffff', fg: v('--text') || '#1d1d1f', line: v('--line2') || '#d0d0d8', mut: v('--muted') || '#777'};
  const all = mm_layout(MM.last.tree, new Set());  // the export shows every branch
  return mm_svg(all, {inline: true, colors}).replace('<svg ', `<svg style="background:${colors.bg}" `);
}
function mm_file(ext) { return (lname(listById(MM.lid)) || 'mindmap').replace(/[\\/:*?"<>|]+/g, '-').slice(0, 60) + '.' + ext; }
function mm_exportPng() {
  const svg = mm_exportSvg(), img = new Image();
  img.onload = () => {
    const c = document.createElement('canvas'), s = 2; c.width = img.width * s; c.height = img.height * s;
    const g = c.getContext('2d'); g.scale(s, s); g.drawImage(img, 0, 0);
    c.toBlob(b => { if (b) mm_download(mm_file('png'), b); else toast(tr('The image could not be made')); }, 'image/png');
  };
  img.onerror = () => toast(tr('The image could not be made'));
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}
function mm_import() {
  const l = listById(MM.lid); if (!l || mm_ro(l)) return;
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.md,.txt,.opml,.mm,.xml,text/markdown,text/plain,text/xml';
  inp.onchange = async () => {
    const f = inp.files?.[0]; if (!f) return;
    if (f.size > 500000) { toast(tr('The file is too large')); return; }
    const text = await f.text(), ext = (f.name.split('.').pop() || '').toLowerCase();
    let tree; try { tree = await rawFetch('POST', '/api/outline/parse', {text, format: ext === 'opml' ? 'opml' : ext === 'mm' ? 'mm' : ext === 'md' || ext === 'txt' ? 'md' : ''}); } catch (e) { toast(e.message); return; }
    await mm_importTree(l, tree);
  };
  inp.click();
}
async function mm_importTree(l, tree) {
  const at = mm_node(MM.sel) || mm_node('r'), base = mm_target(at, 'kid');
  let n = 0, fail = '';
  const add = async (items, where) => {
    for (const it of items) {
      if (fail) return;
      let t; try { t = await api('POST', '/api/tasks', {title: it.title, list_id: l.id, ...where}); } catch (e) { fail = e.message || '!'; return; }
      putTask(t); histCreate(tr('Created {0}', qn(String(t.title).slice(0, 40))), t); n++;
      if (it.children?.length) await add(it.children, {parent_id: t.id});
    }
  };
  await histGroup(() => add(tree.children || [], base), tr('Import of {0} branches', (tree.children || []).length));
  if (at.kind === 'task') { MM.fold.delete(at.id); mm_foldSave(); }
  renderView();
  toast(fail ? tr('{0} branches imported, then stopped: {1}', n, fail) : tr('{0} branches imported', n));
}
function mm_moreMenu(a) {
  const l = listById(MM.lid); if (!l) return;
  menu(a, [{label: tr('Export as Markdown outline'), icon: 'download', fn: () => mm_download(mm_file('md'), new Blob([mm_md(MM.last.tree)], {type: 'text/markdown'}))},
    {label: tr('Export as SVG'), icon: 'download', fn: () => mm_download(mm_file('svg'), new Blob([mm_exportSvg()], {type: 'image/svg+xml'}))},
    {label: tr('Export as PNG'), icon: 'download', fn: mm_exportPng},
    {label: tr('Copy as Markdown outline'), icon: 'copy', fn: () => navigator.clipboard?.writeText(mm_md(MM.last.tree)).then(() => toast(tr('Copied')))},
    ...(mm_ro(l) ? [] : ['-', {label: tr('Import outline (Markdown, OPML, FreeMind)…'), icon: 'upload', fn: mm_import}]),
    '-', {label: tr('Unfold all'), icon: 'expand', fn: () => { MM.fold.clear(); mm_foldSave(); mm_draw(); }}]);
}
function mm_nodeMenu(anchor, n) {  // phones (and the context menu): the actions of a branch in a sheet
  const l = listById(MM.lid), ro = !l || mm_ro(l), task = n.kind === 'task';
  menu(anchor, [...(ro ? [] : [{label: tr('New branch'), icon: 'plus', fn: () => mm_startNew('sib')}, {label: tr('New sub-branch'), icon: 'indent', fn: () => mm_startNew('kid')}]),
    ...(task && !ro ? [{label: tr('Rename'), icon: 'edit', fn: () => mm_rename(n)}] : []),
    ...(task ? [{label: tr('Open task'), icon: 'right', fn: () => openDetail(n.t.id)}] : []),
    ...(n.kids.length && n.kind !== 'root' ? [{label: MM.fold.has(n.id) ? tr('Unfold') : tr('Fold'), icon: MM.fold.has(n.id) ? 'expand' : 'collapse', fn: () => mm_toggle(n.id)}] : []),
    ...(task && !ro && (n.t.parent_id || n.t.section_id) ? [{label: tr('Up a level'), icon: 'outdent', fn: mm_outdent}] : []),
    ...(task && !ro ? ['-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: mm_delete}] : [])], null, null, n.title);
}
// ---- input: keys on the stage, the editor, pointer (select / drag a branch / pan / pinch), wheel zoom
document.addEventListener('keydown', e => {
  const ed = e.target.id === 'mm-edit';
  if (ed) {
    if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
      e.preventDefault(); e.stopPropagation();
      const v = e.target.value, mode = MM.edit?.mode;
      if (e.isComposing) return;
      mm_commit(v).then(() => { if (e.key === 'Tab' && mode !== 'rename' && v.trim()) mm_startNew('kid'); });
    } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); MM.edit = null; mm_draw(); }
    return;
  }
  if (!e.target.classList?.contains('mmstage') || e.ctrlKey || e.metaKey || e.altKey) return;
  const n = mm_node(MM.sel), l = listById(MM.lid), ro = !l || mm_ro(l);
  const k = e.key; let used = true;
  if (k === 'Enter' && !ro) mm_startNew('sib');
  else if (k === 'Tab' && !e.shiftKey && !ro) mm_startNew('kid');
  else if (k === 'Tab' && e.shiftKey && !ro) mm_outdent();
  else if ((k === 'Delete' || k === 'Backspace') && !ro) mm_delete();
  else if (k === ' ') mm_toggle(MM.sel);
  else if (k === 'F2' && !ro && n?.kind === 'task') mm_rename(n)
  else if (k.startsWith('Arrow')) mm_move(k);
  else if (k === 'o' && n?.kind === 'task') openDetail(n.t.id);
  else used = false;
  if (used) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
document.addEventListener('focusout', e => { if (e.target.id === 'mm-edit' && MM.edit && !e.target.dataset.done) { e.target.dataset.done = '1'; mm_commit(e.target.value); } });
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-mm]'); if (!a || !a.closest('.mmwrap')) return;
  const k = a.dataset.mm;
  if (k === 'sib' || k === 'kid') mm_startNew(k);
  else if (k === 'fit') { MM.pan = mm_fitPan(MM.last.L, $('.mmstage')); mm_applyPan(); }
  else if (k === 'more') mm_moreMenu(a);
  else if (k === 'as-map' || k === 'as-outline') { MM.outline = k === 'as-outline'; const o = LS.get('mmOutline', {}) || {}; o[MM.lid] = MM.outline ? 1 : 0; LS.set('mmOutline', o); renderView(); }
  else if (k === 'fold') { e.stopPropagation(); if (MM.fold.has(a.dataset.n)) MM.fold.delete(a.dataset.n); else MM.fold.add(a.dataset.n); mm_foldSave(); renderView(); }
});
// the outline: a tap selects, a second tap opens the branch's actions
document.addEventListener('click', e => {
  const r = e.target.closest?.('.mmoi'); if (!r || e.target.closest('[data-mm]')) return;
  const n = mm_listFind(r.dataset.mmn); if (!n) return;
  if (MM.sel === n.id) mm_nodeMenu(r, n); else { MM.sel = n.id; renderView(); }
});
document.addEventListener('dblclick', e => {
  const g = e.target.closest?.('.mmstage [data-mmn]'); if (!g) return;
  const n = mm_node(g.dataset.mmn), l = listById(MM.lid);
  if (n?.kind === 'task' && l && !mm_ro(l)) { MM.sel = n.id; mm_rename(n); }
});
document.addEventListener('contextmenu', e => {
  const g = e.target.closest?.('.mmstage [data-mmn]'); if (!g) return;
  e.preventDefault(); const n = mm_node(g.dataset.mmn); if (n) { mm_select(n.id); mm_nodeMenu(g, n); }
});
function mm_pt(e) { const st = $('.mmstage').getBoundingClientRect(); return {x: (e.clientX - st.left - MM.pan.x) / MM.pan.k - 16, y: (e.clientY - st.top - MM.pan.y) / MM.pan.k - 16}; }
const mm_hit = p => MM.last.L.nodes.find(n => p.x >= n.x && p.x <= n.x + n.w + 18 && p.y >= n.y && p.y <= n.y + MM_H) || null;
document.addEventListener('pointerdown', e => {
  const st = e.target.closest?.('.mmstage'); if (!st || e.target.id === 'mm-edit' || !MM.pan) return;
  MM.ptr.set(e.pointerId, {x: e.clientX, y: e.clientY});
  try { st.setPointerCapture(e.pointerId); } catch { /* fine */ }
  if (MM.ptr.size === 2) {  // pinch: zoom around the middle of both fingers
    const [a, b] = [...MM.ptr.values()];
    MM.pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), k: MM.pan.k, x: MM.pan.x, y: MM.pan.y, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2};
    MM.drag = null; return;
  }
  const g = e.target.closest('[data-mmn]'), n = g && mm_node(g.dataset.mmn);
  MM.drag = {id: n?.id || null, sx: e.clientX, sy: e.clientY, px: MM.pan.x, py: MM.pan.y, moved: false, over: null, was: MM.sel, lift: false};
  // touch: a long press on a branch lifts it (then the finger rehangs it instead of moving the map)
  const l = listById(MM.lid);
  if (e.pointerType !== 'mouse' && n && n.kind === 'task' && l && !mm_ro(l)) {
    const dd = MM.drag;
    dd.lt = setTimeout(() => { if (MM.drag !== dd || dd.moved) return; dd.lift = true; $(`.mmstage [data-mmn="${dd.id}"]`)?.classList.add('lift'); try { navigator.vibrate?.(10); } catch { /* none */ } }, 450);
  }
  if (!isTouch()) st.focus({preventScroll: true});
});
document.addEventListener('pointermove', e => {
  if (!MM.ptr.has(e.pointerId)) return;
  MM.ptr.set(e.pointerId, {x: e.clientX, y: e.clientY});
  const st = $('.mmstage'); if (!st) return;
  if (MM.pinch && MM.ptr.size >= 2) {
    const [a, b] = [...MM.ptr.values()], p = MM.pinch, r = st.getBoundingClientRect();
    const k = Math.max(0.25, Math.min(2.5, p.k * Math.hypot(a.x - b.x, a.y - b.y) / (p.d || 1))), cx = p.cx - r.left, cy = p.cy - r.top;
    MM.pan = {k, x: cx - (cx - p.x) * k / p.k, y: cy - (cy - p.y) * k / p.k}; mm_applyPan(); return;
  }
  const d = MM.drag; if (!d) return;
  if (!d.moved && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 6) return;
  d.moved = true; clearTimeout(d.lt);
  const l = listById(MM.lid), can = d.id && d.id.startsWith('t') && l && !mm_ro(l) && (e.pointerType === 'mouse' || d.lift);
  if (can) {  // a branch is dragged (mouse; on touch after a long press, else one finger moves the map)
    st.classList.add('mmdragging');
    const h = mm_hit(mm_pt(e)), over = h && h.id !== d.id ? h.id : null;
    if (over !== d.over) { $$('.mmnode.drop', st).forEach(x => x.classList.remove('drop')); d.over = over; if (over) $(`[data-mmn="${over}"]`, st)?.classList.add('drop'); }
    return;
  }
  MM.pan.x = d.px + e.clientX - d.sx; MM.pan.y = d.py + e.clientY - d.sy; mm_applyPan();
});
function mm_up(e) {
  if (!MM.ptr.has(e.pointerId)) return;
  MM.ptr.delete(e.pointerId);
  if (MM.pinch) { if (MM.ptr.size < 2) MM.pinch = null; MM.drag = null; return; }
  const d = MM.drag; MM.drag = null; if (!d) return;
  clearTimeout(d.lt); $$('.mmstage .lift').forEach(x => x.classList.remove('lift'));
  $('.mmstage')?.classList.remove('mmdragging');
  if (d.lift && !d.moved) { mm_select(d.id); return; }
  if (d.moved) { if (d.over && e.type === 'pointerup') mm_rehang(d.id, d.over); else $$('.mmnode.drop').forEach(x => x.classList.remove('drop')); return; }
  if (e.type !== 'pointerup' || !d.id) return;
  if (isTouch() && d.was === d.id) { const g = $(`.mmstage [data-mmn="${d.id}"]`), n = mm_node(d.id); if (g && n) mm_nodeMenu(g, n); return; }
  mm_select(d.id);
}
document.addEventListener('pointerup', mm_up);
document.addEventListener('pointercancel', mm_up);
// bound on the stage itself (a non-passive wheel listener on the whole document would slow every scroll of the app)
function mm_wheel(e) {
  const st = e.currentTarget; if (!MM.pan) return;
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) {  // zoom around the pointer (also the trackpad pinch)
    const r = st.getBoundingClientRect(), cx = e.clientX - r.left, cy = e.clientY - r.top, k0 = MM.pan.k;
    const k = Math.max(0.25, Math.min(2.5, k0 * Math.exp(-e.deltaY / 300)));
    MM.pan = {k, x: cx - (cx - MM.pan.x) * k / k0, y: cy - (cy - MM.pan.y) * k / k0};
  } else { MM.pan.x -= e.deltaX; MM.pan.y -= e.deltaY; }
  mm_applyPan();
}
function mm_bind() { const st = $('.mmstage'); if (st && !st.dataset.wb) { st.dataset.wb = '1'; st.addEventListener('wheel', mm_wheel, {passive: false}); } }
// ---- a ```mindmap block in a knowledge page (display only)
function mm_blockHtml(text) {
  const t = mm_mdTree(text);
  if (!t.kids.length && !t.title) return `<pre class="mdpre">${esc(text)}</pre>`;
  return `<div class="mmblock" role="img" aria-label="${esc(tr('Mind map'))}">${mm_svg(mm_layout(t, new Set()), {})}</div>`;
}
