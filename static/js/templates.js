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
    const name = await askPrompt(tr('Name of the new list'), tp.name, {ok: tr('Create')}); if (name === null) return;
    let j; try { j = await api('POST', `/api/templates/${tp.id}/apply`, {name: name.trim()}); } catch { return; }
    await load(); go('l/' + j.list_id); toast(tr('List created from template')); return;
  }
  const lid = quickDefaults().list_id;
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
    md.remove(); await load(); go('l/' + j.list_id); toast(tr('List created from template'));
  });
  if (!isTouch()) setTimeout(() => $('#tu-name', md).focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
function templateMenu(anchor, kind) {
  const ts = tplOf(kind);
  if (!ts.length) { toast(kind === 'list' ? tr('No list templates yet: list dialog > Save as template') : tr('No task templates yet: task menu > Save as template')); return; }
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
    const lvl = Math.min(2, Math.floor(raw.match(/^\s*/)[0].replace(/\t/g, '  ').length / 2));
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
    : `<div class="row"><label for="tp-lname">${tr('List name')}</label><input id="tp-lname" value="${esc(d.name || '')}"></div>${d.rel ? `<div class="shint keep">${esc(tr('Dates count from the project start (Start + n days); the last task is due on day {0}. Using it asks for the start.', d.span || 0))}${d.deps?.length ? ' ' + esc(trn('{0} dependency is kept.', '{0} dependencies are kept.', d.deps.length)) : ''}</div>` : ''}${d.fields?.length ? `<div class="row"><label>${tr('Custom fields')}</label><span class="muted">${esc(d.fields.map(f => f.name).join(', '))}</span></div>` : ''}<h4>${tr('Sections and tasks')}</h4>`}
    <textarea id="tp-outline" class="tpoutline" rows="9" spellcheck="false">${esc(task ? tplOutline(root.children || []) : tplListOutline(d))}</textarea>
    <div class="shint keep">${task ? tr('One subtask per line, indent with two spaces for a further level (at most 3 levels in total).') : tr('One task per line, indent with two spaces for subtasks. A line “# Name” starts a section.')} ${tr('Lines that keep their title keep their dates, priority and notes.')}</div>
    <div class="foot"><button class="btn danger" data-m="del">${tr('Delete')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('tpmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      if (b.dataset.m === 'del') {
        if (!await askConfirm(tr('Delete the template “{0}”?', tp.name), tr('Lists and tasks made from it stay.'), {ok: tr('Delete'), danger: true})) return;
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
  box.innerHTML = ts.map(tp => `<div class="mrow" data-tpl="${tp.id}"><span class="tplic">${ic(tp.kind === 'list' ? 'list' : 'copy', 's')}</span><span class="n">${esc(tp.name)} <span class="muted">${tp.kind === 'list' ? (tp.data?.rel ? tr('Project') : tr('List')) : tr('Task')} · ${trn('{0} task', '{0} tasks', tp.count)}</span></span><button class="iconbtn" data-tpl-use title="${tr('Use template')}">${ic('plus', 's')}</button><button class="iconbtn" data-tpl-edit title="${tr('Edit template')}">${ic('edit', 's')}</button></div>`).join('')
    || `<div class="muted mhint">${tr('No templates yet. Save one from a task menu (…) or the list dialog: “Save as template”.')}</div>`;
}

// ------------------------------------------------------------------ statistics (module "stats")
// Numbers come from GET /api/stats (per user, last 12 weeks; definitions there), habit rates and streaks
// from the habit history the client already has (same numbers as in the habit dialog). Charts are inline
// SVG drawn at the real pixel width (readable on phones), colours from the theme variables.
S.st = {data: null, loading: false, err: null, v: -1, mode: LS.get('statsMode', 'week')};
async function loadStats() {
  if (S.st.loading) return;
  S.st.loading = true;
  const v = S.v;
  try { S.st.data = await rawFetch('GET', '/api/stats?ws=' + weekStart()); S.st.err = null; S.st.v = v; }
  catch (e) { if (e.message !== 'auth') S.st.err = e instanceof Offline ? 'offline' : e.message; S.st.v = v; }
  finally { S.st.loading = false; }
  if (S.route.mod === 'stats') renderView();
}
const chartW = () => Math.max(260, Math.min(760 * uiZ(), ($('#view')?.clientWidth || 720) - 48));
function niceMax(v) { for (let p = 1; ; p *= 10) for (const m of [2, 4, 6, 10]) if (m * p >= v) return m * p; }  // even: the middle grid line stays a whole number
const topRound = (x, y, w, h, r) => { r = Math.min(r, w / 2, h); return h <= 0 ? '' : `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`; };
const shortDay = s => pd(s).toLocaleDateString(LOCALE(), {day: 'numeric', month: 'short'});
function yGrid(W, padL, padT, ih, max, fmt) {
  return [0, max / 2, max].map(v => { const y = padT + ih - ih * v / max; return `<line class="ch-grid" x1="${padL}" x2="${W}" y1="${y}" y2="${y}"/><text class="ch-ax" x="${padL - 6}" y="${y + 4 * uiZ()}" text-anchor="end">${esc(fmt(v))}</text>`; }).join('');
}
// 2.5.2 (K16): x-axis labels from the right end, each only where it does not touch the one to its right (the width
// comes from the label's length in the mono axis font, so "21. Sept." no longer runs into "28. Sept.")
function axLabels(n, labels, xOf, y, z) {
  let h = '', minL = Infinity;
  for (let i = n - 1; i >= 0; i--) {
    const s = String(labels[i] ?? ''), w = (s.length * 6.9 + 2) * z, x = xOf(i), end = i === n - 1;
    const l = end ? x - w : x - w / 2, r = end ? x : x + w / 2;
    if (!s || r + 8 * z > minL) continue;
    minL = l;
    h += `<text class="ch-ax" x="${x}" y="${y}" text-anchor="${end ? 'end' : 'middle'}">${esc(s)}</text>`;
  }
  return h;
}
function barChart(vals, labels, {fmt = v => String(v), tip, label, w, lw}) {  // w: own width (2.1.1: charts in a dialog); lw: px per axis label (2.5.1)
  const z = uiZ(), W = w || chartW(), H = Math.round(170 * z), padL = Math.round(36 * z), padT = 10, padB = Math.round(24 * z), ih = H - padT - padB, n = vals.length;
  const max = niceMax(Math.max(1, ...vals)), slot = (W - padL) / n, bw = Math.max(4, slot - Math.max(2, Math.min(10, slot * .28)));
  let h = yGrid(W, padL, padT, ih, max, fmt);
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
  const z = uiZ(), W = chartW(), H = Math.round(160 * z), padL = Math.round(36 * z), padT = 12, padB = Math.round(24 * z), ih = H - padT - padB, n = vals.length;
  const max = niceMax(Math.max(1, ...vals)), slot = (W - padL - 12) / Math.max(1, n - 1);
  const X = i => padL + 6 + i * slot, Y = v => padT + ih - ih * v / max;
  let h = yGrid(W, padL, padT, ih, max, v => String(v));
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
function heatmap(weeks, perDay, t0, {unit}) {  // weeks: first days (locale week start); columns = weeks, rows = weekdays
  const z = uiZ(), W = chartW(), lab = Math.round(30 * z), gap = 3, cs = Math.max(10, Math.min(22 * z, Math.floor((W - lab) / weeks.length) - gap));
  const H = 7 * (cs + gap) + Math.round(20 * z), max = Math.max(1, ...Object.values(perDay));
  const lvl = v => !v ? 0 : Math.min(4, Math.ceil(4 * v / max));
  let h = [0, 2, 4, 6].map(r => `<text class="ch-ax" x="${lab - 6}" y="${r * (cs + gap) + cs * .75}" text-anchor="end">${esc(WD[(pd(weeks[0]).getDay() + r) % 7])}</text>`).join('');
  weeks.forEach((w, c) => {
    for (let r = 0; r < 7; r++) {
      const d = addDays(w, r); if (d > t0) continue;
      const v = perDay[d] || 0;
      h += `<rect class="hm l${lvl(v)}" x="${lab + c * (cs + gap)}" y="${r * (cs + gap)}" width="${cs}" height="${cs}" rx="3"><title>${esc(`${fmtDate(d)}: ${unit(v)}`)}</title></rect>`;
    }
  });
  h += `<text class="ch-ax" x="${lab}" y="${H - 4}">${esc(shortDay(weeks[0]))}</text><text class="ch-ax" x="${lab + weeks.length * (cs + gap) - gap}" y="${H - 4}" text-anchor="end">${esc(tr('Today'))}</text>`;
  return `<svg class="chart" width="${Math.min(W, lab + weeks.length * (cs + gap))}" height="${H}" role="img" aria-label="${esc(tr('Completed per day'))}">${h}</svg>
    <div class="hmleg muted">${tr('less')}${[0, 1, 2, 3, 4].map(l => `<i class="hm l${l}"></i>`).join('')}${tr('more')}</div>`;
}
const listLabel = x => x.id === -1 ? tr('No task') : x.id === 0 ? tr('Other lists') : x.is_inbox && inboxDef(x.name) ? tr('Inbox') : listName(x.name);
function viewStats() {
  const st = S.st;
  if ((st.v !== S.v || !st.data) && !st.loading) setTimeout(loadStats, 0);
  const j = st.data;
  if (!j) return `<div class="empty">${st.err ? (st.err === 'offline' ? tr('Statistics are only available online.') : esc(st.err)) : tr('Loading…')}</div>`;
  const wl = j.weeks.map(shortDay), tipW = (i, s) => `${tr('Week of {0}', fmtDate(j.weeks[i]))}: ${s}`;
  const tiles = [
    [j.done.this_week, tr('completed this week'), trn('{0} today', '{0} today', j.done.today)],
    [j.ontime.rate == null ? '–' : j.ontime.rate + '%', tr('on time'), j.ontime.with_due ? tr('{0} of {1} with a date', j.ontime.ontime, j.ontime.with_due) : tr('no completed tasks with a date')],
    [j.streak.current, trn('day in a row', 'days in a row', j.streak.current), tr('best: {0}', j.streak.best)],
    ...(feat('pomo') ? [[fmtH(j.focus.this_week), tr('focus this week'), tr('12 weeks: {0}', fmtH(j.focus.total))]] : []),
    ...(timeOn() && j.time ? [[fmtH(j.time.this_week), tr('tracked this week'), tr('12 weeks: {0}', fmtH(j.time.total))]] : []),
  ];
  const mode = st.mode;
  let h = `<div class="stats"><div class="sttiles">${tiles.map(([v, l, s]) => `<div><b>${esc(String(v))}</b><span>${esc(l)}</span><small>${esc(s)}</small></div>`).join('')}</div>
    <section class="stcard"><div class="sthead"><h3>${tr('Completed tasks')}</h3><span class="muted">${trn('{0} in 12 weeks', '{0} in 12 weeks', j.done.total)}</span><span class="spacer"></span>
      <div class="seg"><button class="${mode === 'week' ? 'on' : ''}" data-act="stats-mode" data-k="week">${tr('Weeks')}</button><button class="${mode === 'day' ? 'on' : ''}" data-act="stats-mode" data-k="day">${tr('Days')}</button></div></div>
      ${mode === 'day' ? heatmap(j.weeks, j.done.per_day, j.today, {unit: v => trn('{0} completed', '{0} completed', v)})
        : barChart(j.done.per_week, wl, {tip: i => tipW(i, trn('{0} completed', '{0} completed', j.done.per_week[i])), label: tr('Completed per week')})}</section>
    <section class="stcard"><div class="sthead"><h3>${tr('By list')}</h3><span class="muted">${tr('last 12 weeks')}</span></div>
      ${hbarChart(j.done.by_list.map(x => ({name: listLabel(x), v: x.n})), {label: tr('Completed by list')})}</section>
    <section class="stcard"><div class="sthead"><h3>${tr('Overdue')}</h3><span class="muted">${trn('{0} overdue now', '{0} overdue now', j.overdue[j.overdue.length - 1].n)}</span></div>
      ${lineChart(j.overdue.map(x => x.n), j.overdue.map((x, i) => i === j.overdue.length - 1 ? tr('Today') : shortDay(x.date)), {label: tr('Overdue tasks at the end of each week'), tip: i => `${i === j.overdue.length - 1 ? tr('Today') : fmtDate(j.overdue[i].date)}: ${trn('{0} overdue', '{0} overdue', j.overdue[i].n)}`})}</section>`;
  if (feat('pomo')) h += `<section class="stcard"><div class="sthead"><h3>${tr('Focus time')}</h3><span class="muted">${tr('12 weeks: {0}', fmtH(j.focus.total))}</span></div>
      ${barChart(j.focus.per_week, wl, {fmt: v => fmtH(Math.round(v)), tip: i => tipW(i, fmtH(j.focus.per_week[i])), label: tr('Focus minutes per week')})}
      <h4>${tr('By list')}</h4>${hbarChart(j.focus.by_list.map(x => ({name: listLabel(x), v: x.minutes})), {fmt: fmtH, label: tr('Focus by list')})}</section>`;
  if (timeOn() && j.time) h += `<section class="stcard"><div class="sthead"><h3>${tr('Tracked time')}</h3><span class="muted">${tr('12 weeks: {0}', fmtH(j.time.total))}</span><span class="spacer"></span><button class="btn sm" data-go="time">${ic('clock', 's')} ${tr('Reports')}</button></div>
      ${barChart(j.time.per_week, wl, {fmt: v => fmtH(Math.round(v)), tip: i => tipW(i, fmtH(j.time.per_week[i])), label: tr('Tracked minutes per week')})}
      <h4>${tr('By list')}</h4>${hbarChart(j.time.by_list.map(x => ({name: listLabel(x), v: x.minutes})), {fmt: fmtH, label: tr('Tracked time by list')})}</section>`;
  const hs = feat('habits') ? S.habits.filter(x => !x.archived) : [];
  if (hs.length) h += `<section class="stcard"><div class="sthead"><h3>${tr('Habits')}</h3></div><div class="sthabits">
      <div class="shh muted"><span></span><span>${tr('rate')}</span><span>${tr('streak')}</span><span>${tr('best')}</span></div>
      ${hs.map(x => { const s = habitStats(x), col = cssColor(x.color) || HCOLORS[0]; return `<div class="shr" data-act="habit-open" data-id="${x.id}" title="${esc(x.per_week ? tr('Share of the last 4 weeks that reached the target') : tr('Share of the scheduled days of the last 30 days'))}"><span class="n"><i class="sw" style="background:${col}"></i>${esc(x.name)}</span>
        <span class="rate"><svg width="64" height="8" viewBox="0 0 64 8" preserveAspectRatio="none" aria-hidden="true"><rect class="ch-track" width="64" height="8" rx="4"/><rect class="ch-bar" width="${Math.round(64 * s.rate / 100)}" height="8" rx="4"/></svg><b>${s.rate}%</b></span><span><b>${s.streak}</b> ${esc(streakUnit(x))}</span><span>${s.best}</span></div>`; }).join('')}</div></section>`;
  h += `<p class="muted stnote">${tr('Last 12 weeks. A completed task counts for the person who ticked it off, also in shared lists; “won’t do” does not count. On time = completed on or before the due day. Overdue = your open tasks (assigned to you, or unassigned in your own lists) whose due date had passed at the end of each week, based on the current due dates.')}</p></div>`;
  return h;
}
let statsResize;
window.addEventListener('resize', () => { if (S.route.mod !== 'stats') return; clearTimeout(statsResize); statsResize = setTimeout(renderView, 150); });
