// @ts-check
/* Kalmido web client: 2.410.0 A (#3514) a choice field marked "Ordered (stages)" in its settings shows its value as a small
   stage bar instead of the text: in the task rows, the columns and on the board cards dots on a line (filled = done, ring =
   the current stage, grey = open) with the name beside them (only the dots on a phone), in the task panel a wide bar with
   the name under every stage and "since …" (the last change of the field in the task's activity). Options marked as a
   special state (red / orange) are no stage of their own: the bar shows them on the stage that follows them in the options
   (the one they hold up; after the last option on the last stage) in their signal colour. Editing stays the menu / select
   of the options. Drawn as inline SVG with the app's colour variables: no start CSS beyond hiding the name on a phone. */
const CFST_SP = {red: ['var(--danger)', 'var(--danger)'], orange: ['var(--st-wait)', 'var(--st-wait-t)']};  // the dot, the text
const CFST_SP_NAMES = [['', N_('Stage')], ['red', N_('Special state red')], ['orange', N_('Special state orange')]];
const cfst_on = f => f?.type === 'select' && !!f.options?.stages && (f.options?.options || []).some(o => !o.special);
/** the stages (options without a special state), the index of the current one (-1 = not set) and the special state */
function cfst_model(f, v) {
  const all = f.options?.options || [], stages = all.filter(o => !o.special), o = all.find(x => x.id === v);
  if (!o) return {stages, cur: -1, sp: null};
  if (!o.special) return {stages, cur: stages.indexOf(o), sp: null};
  const nx = all.slice(all.indexOf(o) + 1).find(x => !x.special);
  return {stages, cur: nx ? stages.indexOf(nx) : stages.length - 1, sp: o};
}
function cfst_label(f, m) {  // "Build: Stage 3 of 5: Review" (aria-label and tooltip)
  if (m.cur < 0) return f.name + ': ' + tr('empty');
  return f.name + ': ' + tr('Stage {0} of {1}: {2}', m.cur + 1, m.stages.length, (m.sp || m.stages[m.cur]).name);
}
const cfst_ink = m => m.sp ? CFST_SP[m.sp.special]?.[1] || 'var(--accent)' : 'var(--accent)';
// one dot: d = done, c = current (a ring), o = open, s = a special state; x / y in the units of the svg (or "50%")
function cfst_dot(m, i, x, y, k) {
  if (i === m.cur && m.sp) return `<circle class="s" cx="${x}" cy="${y}" r="${4 * k}" style="fill:${CFST_SP[m.sp.special]?.[0]}"/>`;
  if (i === m.cur) return `<circle class="c" cx="${x}" cy="${y}" r="${3.75 * k}" stroke-width="${1.5 * k}" style="fill:var(--bg);stroke:var(--accent)"/><circle cx="${x}" cy="${y}" r="${1.75 * k}" style="fill:var(--accent)"/>`;
  if (i < m.cur) return `<circle class="d" cx="${x}" cy="${y}" r="${3 * k}" style="fill:var(--accent)"/>`;
  return `<circle class="o" cx="${x}" cy="${y}" r="${2.75 * k}" stroke-width="${1.25 * k}" style="fill:var(--bg);stroke:var(--bg4)"/>`;
}
const cfst_line = (i, m) => `style="stroke:${i <= m.cur ? 'var(--accent)' : 'var(--line2)'}"`;
// ---- the small bar: a task row's field, a column cell, a board card. cell = a column (an empty field shows grey dots)
function cfstChip(f, v, cell) {
  const m = cfst_model(f, v); if (m.cur < 0 && !cell) return '';
  const n = m.stages.length, g = 10, w = (n - 1) * g + 10, lab = cfst_label(f, m);
  let s = '';
  for (let i = 1; i < n; i++) s += `<line x1="${(i - 1) * g + 5}" y1="5" x2="${i * g + 5}" y2="5" stroke-width="1.5" ${cfst_line(i, m)}/>`;
  for (let i = 0; i < n; i++) s += cfst_dot(m, i, i * g + 5, 5, 1);
  return `<span class="cfst" role="img" aria-label="${esc(lab)}" title="${esc(lab)}" data-stage="${m.cur + 1}" data-stages="${n}"${m.sp ? ` data-sp="${esc(m.sp.special)}"` : ''}>`
    + `<svg width="${w}" height="10" viewBox="0 0 ${w} 10" aria-hidden="true" focusable="false">${s}</svg>`
    + (m.cur < 0 ? '' : `<span class="cfst-l" style="color:${cfst_ink(m)}">${esc((m.sp || m.stages[m.cur]).name)}</span>`) + '</span>';
}
// ---- the task panel: the wide bar under the field's select, a name under every stage, "since …" below
function cfstWide(f, t) {
  const m = cfst_model(f, t.fields?.[f.id]), n = m.stages.length, x = i => ((i + .5) / n * 100).toFixed(2) + '%', lab = cfst_label(f, m);
  let s = '';
  for (let i = 1; i < n; i++) s += `<line x1="${x(i - 1)}" y1="9" x2="${x(i)}" y2="9" stroke-width="2.5" ${cfst_line(i, m)}/>`;
  for (let i = 0; i < n; i++) s += cfst_dot(m, i, x(i), 9, 1.7);
  const names = m.stages.map((o, i) => {
    const sp = i === m.cur && m.sp, col = sp ? cfst_ink(m) : i <= m.cur ? 'var(--accent)' : 'var(--muted)';
    return `<span style="flex:1 1 0;min-width:0;text-align:center;overflow-wrap:anywhere;color:${col}${i === m.cur ? ';font-weight:600' : ''}"${sp ? ` title="${esc(o.name)}"` : ''}>${esc(sp ? m.sp.name : o.name)}</span>`;
  }).join('');
  return `<div class="cfstw" role="img" aria-label="${esc(lab)}" data-stage="${m.cur + 1}" data-stages="${n}"${m.sp ? ` data-sp="${esc(m.sp.special)}"` : ''} style="grid-column:1/-1;margin:-.125rem 0 .25rem">`
    + `<svg width="100%" height="18" aria-hidden="true" focusable="false" style="display:block;overflow:visible">${s}</svg>`
    + `<div aria-hidden="true" style="display:flex;gap:.25rem;margin-top:.25rem;font-size:var(--fs-s)">${names}</div>`
    + `<div class="cfstw-m muted" data-cfst-since="${f.id}" style="text-align:center;font-size:var(--fs-s);margin-top:.25rem">${esc(cfst_sinceText(f, t))}</div></div>`;
}
// "since 10:52": when the field got its value - the task's field_at (the server's time of the last change, 2.410.0 B), else
// the newest change of the field in the task's activity (loaded with the comments), else the task's creation once the
// activity is known; before that no line (cfst_since fills it in)
function cfst_sinceText(f, t) {
  if (cfst_model(f, t.fields?.[f.id]).cur < 0) return '';
  let at = t.field_at?.[f.id];
  if (!at && S.tl?.id === t.id && S.tl.activity) at = (S.tl.activity.filter(x => x.kind === 'field' && x.data?.id === f.id).pop() || {}).created_at || t.created_at;
  return at ? tr('since {0}', fmtWhen(at)) : '';
}
function cfst_since() {  // collab.js drawTimeline: the activity arrived after the panel was drawn
  const t = taskById(S.sel); if (!t) return;
  for (const el of $$('#detail [data-cfst-since]')) { const f = fieldById(+(/** @type {HTMLElement} */ (el).dataset.cfstSince || 0)); if (f) el.textContent = cfst_sinceText(f, t); }
}
// ---- the field dialog (projects.js fieldModal): "Ordered (stages)" and per option whether it is a special state
function cfst_dlgRow(st) {
  return `<div class="row"><label>${tr('Display')}</label><label class="chkl"><input type="checkbox" id="fd-stages" ${st.stages ? 'checked' : ''}> ${tr('Ordered (stages): show as a stage bar')}</label></div>`;
}
function cfst_optSel(o, i) {
  return `<select data-osp="${i}" aria-label="${esc(tr('Kind of the option'))}" title="${esc(tr('A special state (e.g. Parked) is no stage of its own: the bar shows it in its colour on the next stage.'))}" style="width:auto;flex:none">${CFST_SP_NAMES.map(([k, n]) => `<option value="${k}" ${(o.special || '') === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>`;
}
