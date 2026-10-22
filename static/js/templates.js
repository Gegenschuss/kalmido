/* Kalmido web client: Templates and statistics.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ templates (private per user)
// A task (subtasks, priority, tags, notes, repeat; dates as days after the day it was saved) or a whole
// list (sections + open tasks). Using one puts the dates relative to today. Settings > Data manages them.
const tplOf = kind => (S.templates || []).filter(x => x.kind === kind);
async function saveTemplate(src, def) {
  const name = await askPrompt(tr('Template name'), def || '', {ok: tr('Save as template')});
  if (name === null) return;
  try { await api('POST', '/api/templates', {...src, name: name.trim()}); } catch { return; }
  await load(); render(); toast(tr('Saved as template'));
}
async function useTemplate(tp) {
  if (tp.kind === 'list') {
    if (!tp.data) { try { tp = (await api('GET', '/api/templates')).templates.find(x => x.id === tp.id) || tp; } catch { /* offline: as before */ } }
    if (tp.data?.rel) { tplUseModal(tp); return; }  // 2.4.0 (#328): a project template asks for the start (and an optional end)
    const name = await askPrompt(tr('Name of the new project'), tp.name, {ok: tr('Create')}); if (name === null) return;
    let j; try { j = await api('POST', `/api/templates/${tp.id}/apply`, {name: name.trim()}); } catch { return; }
    await load(); go('l/' + j.list_id); toast(tr('Project created from template')); return;
  }
  const lid0 = quickDefaults().list_id, lid = listById(lid0)?.e2e ? null : lid0;  // 2.64.1 (#1817): a template never lands in a locked list (the basket instead)
  let j; try { j = await api('POST', `/api/templates/${tp.id}/apply`, {list_id: lid && canEditList(lid) ? lid : null}); } catch { return; }
  putTask(j.task); await load(); render();
  const id = j.task.id;
  requestAnimationFrame(() => { const r = $(`#view .trow[data-id="${id}"]`); if (r) { r.classList.add('flash'); r.scrollIntoView({block: 'nearest'}); } });
  offerUndo(tr('Created from template: {0}', tp.name), histCreate(tr('Created from template: {0}', tp.name), {...j.task, created_at: j.task.created_at}));
}
// 2.4.0 (#328): a project from a template with dates relative to its start: name, folder, start, optional end (the dates
// are stretched or squeezed so the last one falls on the end), dependencies and sections kept
function tplUseModal(tp) {
  const span = tp.data?.span || 0;
  const md = modal(`<h3>${tr('New project from “{0}”', esc(tp.name))}</h3>
    <div class="row"><label for="tu-name">${tr('Name')}</label><input id="tu-name" value="${esc(tp.data?.name || tp.name)}" maxlength="200"></div>
    <div class="row"><label for="tu-folder">${tr('Folder')}</label><input id="tu-folder" list="tu-folders" placeholder="${esc(tr('optional · Folder / Subfolder'))}"><datalist id="tu-folders">${folderNames().map(f => `<option value="${esc(fDisp(f))}">`).join('')}</datalist></div>
    <div class="row"><label>${tr('Project start')}</label>${dateIn('tu-start', today(), {label: tr('Project start'), clear: false})}</div>
    ${span ? `<div class="row"><label>${tr('End (optional)')}</label>${dateIn('tu-end', '', {label: tr('End (optional)'), empty: tr('none')})}<span class="muted" id="tu-hint">${esc(tr('As saved: {0} days', span))}</span></div>` : ''}
    <div class="shint">${tr('Every date keeps its distance to the project start. With an end date the dates are stretched or squeezed to fit. Sections, fields and dependencies come along.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Create')}</button></div>`);
  md.classList.add('tumodal');
  const hint = () => { const h = $('#tu-hint', md), s0 = $('#tu-start', md).value, e0 = $('#tu-end', md)?.value; if (!h) return; h.textContent = s0 && e0 && e0 >= s0 ? tr('{0} days instead of {1}', Math.round((pd(e0) - pd(s0)) / 864e5), span) : tr('As saved: {0} days', span); };
  md.addEventListener('input', hint); md.addEventListener('change', hint);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const name = $('#tu-name', md).value.trim(); if (!name) { need($('#tu-name', md)); return; }
    const end = $('#tu-end', md)?.value || '';
    if (end && end < $('#tu-start', md).value) { toast(tr('The end date is before the start date')); return; }
    let j; try { j = await api('POST', `/api/templates/${tp.id}/apply`, {name, folder: fNorm($('#tu-folder', md).value), start: $('#tu-start', md).value || today(), ...(end ? {end} : {})}); } catch { return; }
    md.remove(); await load(); go('l/' + j.list_id); toast(tr('Project created from template'));
  });
  if (!isTouch()) setTimeout(() => $('#tu-name', md).focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
// 2.78.0 (#1881): "Duplicate list…" (list menu, list dialog): a copy of the list as a list template used at once (server
// POST /api/lists/{id}/duplicate): sections, tasks with their dates, notepads, page arrangement and colours; members and shares stay
const dupOk = l => !!l && !l.is_inbox && !l.archived && !l.e2e && canEditList(l.id);  // N35: not for locked lists; 2.126.0 D (#1992 A6): only who may edit the list
function listDuplicate(id) {
  const l = listById(id); if (!dupOk(l)) return;
  const md = modal(`<h3>${tr('Duplicate “{0}”', esc(lname(l)))}</h3>
    <div class="row"><label for="ld-name">${tr('Name')}</label><input id="ld-name" value="${esc(tr('{0} (copy)', lname(l)))}" maxlength="200"></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="ld-done"> ${tr('Copy completed tasks too')}</label></div>
    <div class="shint keep">${tr('Sections, tasks with subtasks and dates, fields, notepads and the page arrangement come along. Members, shares and assignees do not: the copy is yours alone.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Duplicate')}</button></div>`);
  md.classList.add('ldmodal');
  const go_ = async () => {
    const name = $('#ld-name', md).value.trim(); if (!name) { need($('#ld-name', md)); return; }
    const b = $('[data-m="ok"]', md); if (b.disabled) return; b.disabled = true;
    let j; try { j = await api('POST', `/api/lists/${id}/duplicate`, {name, done: $('#ld-done', md).checked}); } catch { b.disabled = false; return; }
    md.remove(); await load(); go('l/' + j.list_id); toast(tr('Project duplicated'));
  };
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove(); else if (b.dataset.m === 'ok') go_();
  });
  $('#ld-name', md).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go_(); } });
  if (!isTouch()) setTimeout(() => { const n = $('#ld-name', md); n.focus(); n.select(); }, 50);
}
function templateMenu(anchor, kind) {
  const ts = tplOf(kind);
  if (!ts.length) { toast(kind === 'list' ? tr('No project templates yet: project dialog > Save as template') : tr('No task templates yet: task menu > Save as template')); return; }
  menu(anchor, [...ts.map(tp => ({label: tp.name, icon: kind === 'list' ? 'list' : 'copy', fn: () => useTemplate(tp)})), '-', {label: tr('Manage templates'), icon: 'edit', fn: () => settingsModal('templates')}]);
}
// outline editor: one task per line, two spaces = one level deeper, "# Name" = section (list templates).
// Lines that keep their title keep their dates, priority, notes etc.
const tplOutline = (nodes, lvl = 0) => nodes.map(n => '  '.repeat(lvl) + n.title + '\n' + tplOutline(n.children || [], lvl + 1)).join('');
function tplListOutline(d) {
  const top = (d.tasks || []).filter(n => n.section == null);
  return tplOutline(top) + (d.sections || []).map((s, i) => `# ${s}\n` + tplOutline((d.tasks || []).filter(n => n.section === i))).join('');
}
function tplParse(text, old, list) {
  const pool = new Map();
  const add = n => { if (!pool.has(n.title)) pool.set(n.title, []); pool.get(n.title).push(n); (n.children || []).forEach(add); };
  old.forEach(add);
  const take = title => { const n = (pool.get(title) || []).shift(); return n ? {...n, title, children: []} : {title, children: []}; };
  const roots = [], sections = [], stack = [];
  let sec = null;
  for (const raw of String(text).split('\n')) {
    if (!raw.trim()) continue;
    if (list && /^#\s*\S/.test(raw)) { sections.push(raw.replace(/^#\s*/, '').trim().slice(0, 200)); sec = sections.length - 1; stack.length = 0; continue; }
    const lvl = Math.min(maxDepth() - (list ? 1 : 2), Math.floor(raw.match(/^\s*/)[0].replace(/\t/g, '  ').length / 2));
    const title = raw.trim().replace(/^[-*]\s+(\[[ xX]\]\s+)?/, '').slice(0, 500);
    if (!title) continue;
    const n = take(title), depth = Math.min(lvl, stack.length);
    stack.length = depth;
    if (depth === 0) { if (list) n.section = sec; else delete n.section; roots.push(n); } else stack[depth - 1].children.push(n);
    stack.push(n);
  }
  return {roots, sections};
}
function templateModal(tp, done) {
  const d = JSON.parse(JSON.stringify(tp.data)), task = tp.kind === 'task', root = task ? d.task : null;
  const prios = [[0, N_('None')], [1, N_('Low')], [3, N_('Medium')], [5, N_('High')]];
  const md = modal(`<h3>${tr('Edit template')}</h3>
    <div class="row"><label for="tp-name">${tr('Template name')}</label><input id="tp-name" value="${esc(tp.name)}" maxlength="200"></div>
    ${task ? `<div class="row"><label for="tp-title">${tr('Title')}</label><input id="tp-title" value="${esc(root.title)}"></div>
      <div class="row"><label for="tp-content">${tr('Description')}</label><textarea id="tp-content" rows="3">${esc(root.content || '')}</textarea></div>
      <div class="row"><label for="tp-prio">${tr('Priority')}</label><select id="tp-prio">${prios.map(([v, n]) => `<option value="${v}" ${root.priority === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      <div class="row"><label for="tp-due">${tr('Due')}</label><input type="number" id="tp-due" min="0" max="3650" value="${root.due_offset ?? ''}" placeholder="–" style="max-width:5rem"><span class="muted" style="font-size:var(--fs-s)">${tr('days after use (0 = same day, empty = no date)')}</span></div>
      <div class="row"><label>${tr('Time')}</label>${timeIn('tp-time', root.due_time || '', {label: tr('Time'), empty: tr('all day')})}${root.repeat ? `<span class="muted" style="font-size:var(--fs-s)">${ic('repeat', 's')} ${esc(repeatLabel(root.repeat))}</span>` : ''}</div>
      <div class="row"><label for="tp-tags">${tr('Tags')}</label><input id="tp-tags" value="${esc((root.tags || []).join(', '))}" placeholder="${tr('tag1, tag2')}"></div>
      <h4>${tr('Subtasks')}</h4>`
    : `<div class="row"><label for="tp-lname">${tr('Project name')}</label><input id="tp-lname" value="${esc(d.name || '')}"></div>${d.rel ? `<div class="shint keep">${esc(tr('Dates count from the project start (Start + n days); the last task is due on day {0}. Using it asks for the start.', d.span || 0))}${d.deps?.length ? ' ' + esc(trn('{0} dependency is kept.', '{0} dependencies are kept.', d.deps.length)) : ''}</div>` : ''}${d.fields?.length ? `<div class="row"><label>${tr('Custom fields')}</label><span class="muted">${esc(d.fields.map(f => f.name).join(', '))}</span></div>` : ''}<h4>${tr('Sections and tasks')}</h4>`}
    <textarea id="tp-outline" class="tpoutline" rows="9" spellcheck="false">${esc(task ? tplOutline(root.children || []) : tplListOutline(d))}</textarea>
    <div class="shint keep">${task ? tr('One subtask per line, indent with two spaces for a further level (at most {0} levels in total).', maxDepth()) : tr('One task per line, indent with two spaces for subtasks. A line “# Name” starts a section.')} ${tr('Lines that keep their title keep their dates, priority and notes.')}</div>
    <div class="foot"><button class="btn danger" data-m="del">${tr('Delete')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('tpmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      if (b.dataset.m === 'del') {
        if (!await askConfirm(tr('Delete the template “{0}”?', tp.name), tr('Projects and tasks made from it stay.'), {ok: tr('Delete'), danger: true})) return;
        await api('DELETE', '/api/templates/' + tp.id);
      }
      if (b.dataset.m === 'save') {
        const name = $('#tp-name', md).value.trim(); if (!name) { need($('#tp-name', md)); return; }
        let data;
        if (task) {
          const title = $('#tp-title', md).value.trim(); if (!title) { need($('#tp-title', md)); return; }
          const due = $('#tp-due', md).value.trim();
          data = {task: {...root, title, content: $('#tp-content', md).value, priority: +$('#tp-prio', md).value,
            due_offset: due === '' ? null : Math.max(0, +due), due_time: due === '' ? null : $('#tp-time', md).value || null,
            tags: $('#tp-tags', md).value.split(',').map(x => x.trim().replace(/^#/, '')).filter(Boolean),
            children: tplParse($('#tp-outline', md).value, root.children || [], false).roots}};
        } else {
          const p = tplParse($('#tp-outline', md).value, d.tasks || [], true);
          data = {...d, name: $('#tp-lname', md).value.trim(), sections: p.sections, tasks: p.roots};
        }
        await api('PATCH', '/api/templates/' + tp.id, {name, data});
      }
    } catch { return; }  // api() showed it
    md.remove(); await load(); render(); done && done(); toast(b.dataset.m === 'del' ? tr('Template deleted') : tr('Saved'));
  });
  if (!isTouch()) setTimeout(() => $('#tp-name', md).focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
async function templatesDraw(md) {
  const box = $('#s-tpls', md); if (!box) return;
  let ts;
  try { ts = (await api('GET', '/api/templates')).templates; } catch { box.innerHTML = `<div class="muted mhint">${tr('Templates are only available online.')}</div>`; return; }
  box._t = ts;
  box.innerHTML = ts.map(tp => `<div class="mrow" data-tpl="${tp.id}"><span class="tplic">${ic(tp.kind === 'list' ? 'list' : 'copy', 's')}</span><span class="n">${esc(tp.name)} <span class="muted">${tp.kind === 'list' ? (tp.data?.rel ? tr('Project') : tr('Project')) : tr('Task')} · ${trn('{0} task', '{0} tasks', tp.count)}</span></span><button class="iconbtn" data-tpl-use title="${tr('Use template')}">${ic('plus', 's')}</button><button class="iconbtn" data-tpl-edit title="${tr('Edit template')}">${ic('edit', 's')}</button></div>`).join('')
    || `<div class="muted mhint">${tr('No templates yet. Save one from a task menu (…) or the project dialog: “Save as template”.')}</div>`;
}

// ------------------------------------------------------------------ statistics (module "stats")
// Numbers come from GET /api/stats (per user, last 12 weeks; definitions there), habit rates and streaks
// from the habit history the client already has (same numbers as in the habit dialog). Charts are inline
// SVG drawn at the real pixel width (readable on phones), colours from the theme variables.
// 2.65.0 (#1823): the view itself (viewStats, loadStats, heatmap) is in stats.js, loaded on demand
const chartW = () => Math.max(260, Math.min(760 * uiZ(), ($('#view')?.clientWidth || 720) - 48));
function niceMax(v) { for (let p = 1; ; p *= 10) for (const m of [2, 4, 6, 10]) if (m * p >= v) return m * p; }  // even: the middle grid line stays a whole number
const topRound = (x, y, w, h, r) => { r = Math.min(r, w / 2, h); return h <= 0 ? '' : `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`; };
const shortDay = s => pd(s).toLocaleDateString(LOCALE(), {day: 'numeric', month: 'short'});
// 2.39.1 (#1180): round axis steps, at most 4: counts 1 / 2 / 5 x 10^n; time (minutes) 5 / 10 / 15 / 30 min, then 1 / 2 / 5 x 10^n h
// (no more "33h 20m" on the axis); the axis column is as wide as its longest label (nothing cut off on a phone)
function mx_ticks(v, time) {
  v = Math.max(1, v); const ok = s => Math.ceil(v / s) <= 4;
  let s = time ? [5, 10, 15, 30].find(ok) : 0;
  for (let p = 1; !s; p *= 10) for (const m of [1, 2, 5]) if (!s && ok(m * p * (time ? 60 : 1))) s = m * p * (time ? 60 : 1);
  const n = Math.max(1, Math.ceil(v / s));
  return {max: n * s, ticks: [...Array(n + 1)].map((_, i) => i * s)};
}
const mx_axH = m => m % 60 ? `${m} min` : `${m / 60} h`;
const mx_padL = (ticks, fmt, z) => Math.max(Math.round(28 * z), Math.round((Math.max(...ticks.map(t => String(fmt(t)).length)) * 6.6 + 10) * z));
function yGrid(W, padL, padT, ih, max, fmt, ticks = [0, max / 2, max]) {
  return ticks.map(v => { const y = padT + ih - ih * v / max; return `<line class="ch-grid" x1="${padL}" x2="${W}" y1="${y}" y2="${y}"/><text class="ch-ax" x="${padL - 6}" y="${y + 4 * uiZ()}" text-anchor="end">${esc(fmt(v))}</text>`; }).join('');
}
// 2.5.2 (K16): x-axis labels from the right end, each only where it does not touch the one to its right
// 2.39.1 (#1180): every k-th label, the same k across the axis (even gaps: no more 20 Jul, 3 Aug, 24 Aug); k from the widest
// label (the last one is right-aligned, so it needs 1.5 widths of room)
function axLabels(n, labels, xOf, y, z) {
  const mw = Math.max(0, ...labels.slice(0, n).map(s => (String(s ?? '').length * 6.4 + 2) * z)), d = n > 2 ? Math.abs(xOf(n - 2) - xOf(n - 3)) || 1 : n > 1 ? Math.abs(xOf(1) - xOf(0)) || 1 : 1;  // not the last pair: it is right-aligned
  const k = Math.max(1, Math.ceil((mw * 1.5 + 8 * z) / d));
  let h = '';
  for (let i = n - 1; i >= 0; i -= k) {
    const s = String(labels[i] ?? ''), x = xOf(i), end = i === n - 1;
    if (s) h += `<text class="ch-ax" x="${x}" y="${y}" text-anchor="${end ? 'end' : 'middle'}">${esc(s)}</text>`;
  }
  return h;
}
function barChart(vals, labels, {fmt = v => String(v), tip, label, w, lw, time}) {  // w: own width (2.1.1: charts in a dialog); lw: px per axis label (2.5.1); time: minutes (2.39.1)
  const z = uiZ(), W = w || chartW(), {max, ticks} = mx_ticks(Math.max(...vals), time), axf = time ? mx_axH : fmt;
  const H = Math.round(170 * z), padL = mx_padL(ticks, axf, z), padT = 10, padB = Math.round(24 * z), ih = H - padT - padB, n = vals.length;
  const slot = (W - padL) / n, bw = Math.max(4, slot - Math.max(2, Math.min(10, slot * .28)));
  let h = yGrid(W, padL, padT, ih, max, axf, ticks);
  const bx = i => padL + i * slot + (slot - bw) / 2;
  h += axLabels(n, labels, i => i === n - 1 ? bx(i) + bw : bx(i) + bw / 2, H - 6 * z, z);  // 2.5.1: the last label inside the chart
  vals.forEach((v, i) => {
    const x = bx(i), bh = ih * v / max;
    h += `<path class="ch-bar" d="${topRound(x, padT + ih - bh, bw, bh, 4)}"/>`;
    h += `<rect class="ch-hit" x="${padL + i * slot}" y="${padT}" width="${slot}" height="${ih}"><title>${esc(tip(i))}</title></rect>`;
  });
  return `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label + ': ' + vals.map((v, i) => tip(i)).join('; '))}">${h}</svg>`;
}
function lineChart(vals, labels, {tip, label}) {
  const z = uiZ(), W = chartW(), {max, ticks} = mx_ticks(Math.max(...vals)), H = Math.round(160 * z), padL = mx_padL(ticks, String, z), padT = 12, padB = Math.round(24 * z), ih = H - padT - padB, n = vals.length;
  const slot = (W - padL - 12) / Math.max(1, n - 1);
  const X = i => padL + 6 + i * slot, Y = v => padT + ih - ih * v / max;
  let h = yGrid(W, padL, padT, ih, max, v => String(v), ticks);
  h += `<polyline class="ch-line" points="${vals.map((v, i) => `${X(i)},${Y(v)}`).join(' ')}"/>`;
  h += axLabels(n, labels, X, H - 6 * z, z);
  vals.forEach((v, i) => {
    h += `<circle class="ch-dot" cx="${X(i)}" cy="${Y(v)}" r="4"/>`;
    h += `<rect class="ch-hit" x="${X(i) - slot / 2}" y="${padT}" width="${slot}" height="${ih}"><title>${esc(tip(i))}</title></rect>`;
  });
  return `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label + ': ' + vals.map((v, i) => tip(i)).join('; '))}">${h}</svg>`;
}
function hbarChart(rows, {fmt = v => String(v), label, w}) {  // rows: [{name, v}]
  if (!rows.length) return `<div class="muted stempty">${tr('Nothing in this period.')}</div>`;
  const z = uiZ(), W = w || chartW(), rh = Math.round(30 * z), H = rows.length * rh, labW = Math.min(170 * z, W * .38), valW = Math.round(58 * z), bw = W - labW - valW, cy = rh / 2;
  const max = Math.max(1, ...rows.map(r => r.v));
  const cut = s => s.length > 24 ? s.slice(0, 23) + '…' : s;
  return `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label + ': ' + rows.map(r => `${r.name} ${fmt(r.v)}`).join('; '))}">${rows.map((r, i) => {
    const y = i * rh, w = Math.max(3, bw * r.v / max);
    const t = y + cy + 4 * z, b0 = y + cy - 8 * z, b1 = y + cy + 8 * z;  // text baseline, bar top / bottom
    return `<text class="ch-lab" x="0" y="${t}">${esc(cut(r.name))}</text><path class="ch-bar" d="M${labW},${b0}H${labW + w - 4}Q${labW + w},${b0} ${labW + w},${b0 + 4}V${b1 - 4}Q${labW + w},${b1} ${labW + w - 4},${b1}H${labW}Z"/><text class="ch-val" x="${labW + w + 8}" y="${t}">${esc(fmt(r.v))}</text><rect class="ch-hit" x="0" y="${y}" width="${W}" height="${rh}"><title>${esc(r.name + ': ' + fmt(r.v))}</title></rect>`;
  }).join('')}</svg>`;
}
