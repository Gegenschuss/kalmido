'use strict';
// 2.60.0 B (#1510): WIP limits of kanban columns (sections.wip_limit; null = none). A hint only: the column head shows
// "2/3" and is marked above the limit, a move into a full column says so, moving stays allowed. Set in the column menu,
// one undo step.
const wip_sec = sid => sid ? S.sections.find(x => x.id === sid) : null;
const wip_open = sid => openTasks().filter(t => t.section_id === sid && !t.parent_id).length;
function wip_count(n, lim) {
  return `<span class="c wipc${n > lim ? ' wip-over' : n === lim ? ' wip-full' : ''}" title="${esc(tr('{0} open of at most {1} (WIP limit)', n, lim))}">${n}/${lim}</span>`;
}
// the count in a kanban column head: "2/3" with a limit (marked above it)
function wip_kHead(c) {
  const lim = wip_sec(c.id)?.wip_limit, n = c.tasks.length;
  return lim ? wip_count(n, lim) : `<span class="c">${n}</span>`;
}
// the list view's section head: only the limit (the plain count is there already)
function wip_ghead(g) {
  const lim = wip_sec(g.section)?.wip_limit;
  return lim ? wip_count(wip_open(g.section), lim) : '';
}
// a move into a column over its limit says so in the move's message (moving stays allowed)
function wip_msg(msg, sid) {
  const lim = wip_sec(sid)?.wip_limit, n = lim ? wip_open(sid) : 0;
  return lim && n > lim ? msg + ' · ' + tr('Over the WIP limit ({0}/{1})', n, lim) : msg;
}
const wip_menuItem = sid => ({label: wip_sec(sid)?.wip_limit ? tr('WIP limit: {0}', wip_sec(sid).wip_limit) : tr('WIP limit…'), icon: 'chart', fn: () => wip_set(sid)});
async function wip_set(sid) {
  const s = wip_sec(sid); if (!s) return;
  const v0 = s.wip_limit ?? null;
  const raw = await askPrompt(tr('WIP limit of {0}', s.name), v0 ? String(v0) : '', {ok: tr('Save'),
    body: tr('The most open tasks this column should hold. Above it the column head is marked; moving stays allowed. Empty = no limit.'),
    input: {type: 'number', placeholder: tr('No limit')}});
  if (raw == null) return;
  const n = parseInt(String(raw).trim(), 10), v = n > 0 ? Math.min(n, 999) : null;
  if (v === v0) return;
  try { await optWrite(optSet(() => wip_sec(sid), {wip_limit: v}), () => api('PATCH', '/api/sections/' + sid, {wip_limit: v})); } catch { return; }
  const go = (to, from) => async e => {
    const r = await api('PATCH', '/api/sections/' + secId(e.sid), {wip_limit: to, _prev: {wip_limit: from}});
    if (r.conflicts?.length) return {skipped: [tr('Section {0}', qn(s.name.slice(0, 40)))], none: true};
    const x = wip_sec(secId(e.sid)); if (x) x.wip_limit = to;
    return {};
  };
  offerUndo(v ? tr('WIP limit of {0}: {1}', qn(s.name.slice(0, 40)), v) : tr('WIP limit of {0} removed', qn(s.name.slice(0, 40))),
    histAdd({label: tr('WIP limit of {0}', qn(s.name.slice(0, 40))), lids: [s.list_id], sid, undo: go(v0, v), redo: go(v, v0)}));
}


// 2.410.0 B (#3515): how long a card is in its board column ("3 h", "2 d"): since tasks.section_at (a linked task: its place in
// this list), else since it was created. Above the column's limits (sections.dwell_warn_h / dwell_alert_h, hours) the time
// turns yellow / red, without a limit it stays grey. Worked out when the board draws (minutes), no ticking clock.
const dw_since = (t, lid) => (t.list_id === lid ? t.section_at : ml_of(t, lid)?.section_at) || t.created_at || null;
function dw_text(min) {
  if (min < 60) return tr('{0} min|dwell', min);
  return min < 1440 ? tr('{0} h|dwell', Math.floor(min / 60)) : tr('{0} d|dwell', Math.floor(min / 1440));
}
// the level of a time in a column: '' (grey), 'warn' or 'alert'
function dw_level(min, s) {
  const h = min / 60;
  return s?.dwell_alert_h && h > s.dwell_alert_h ? 'alert' : s?.dwell_warn_h && h > s.dwell_warn_h ? 'warn' : '';
}
// the card's mark in the meta line (taskRow opts.dwell = the board's list)
function dw_chip(t, lid) {
  const at = t.status === 0 && t.id > 0 ? dw_since(t, lid) : null, ms = at ? Date.parse(at) : NaN;
  if (!Number.isFinite(ms)) return '';
  const min = Math.max(0, Math.floor((Date.now() - ms) / 6e4)), lv = dw_level(min, wip_sec(ml_sec(t, lid))), txt = dw_text(min);
  const tip = tr('In this column for {0}', txt) + (lv === 'alert' ? ' · ' + tr('Over the red limit') : lv === 'warn' ? ' · ' + tr('Over the yellow limit') : '');
  return `<span class="dwm${lv ? ' dw-' + lv : ''}" data-dw="${lv || 'ok'}" title="${esc(tip)}">${ic('timer', 's')}${esc(txt)}<span class="sr"> ${esc(tip)}</span></span>`;
}
const dw_limText = h => h % 24 ? tr('{0} h|dwell', h) : tr('{0} d|dwell', h / 24);
const dw_menuItem = sid => { const s = wip_sec(sid), w = s?.dwell_warn_h, a = s?.dwell_alert_h;
  return {label: w || a ? tr('Time limits: {0}', [w && dw_limText(w), a && dw_limText(a)].filter(Boolean).join(' / ')) : tr('Time limits…'), icon: 'timer', fn: () => dw_setLim(sid)}; };
// one row of the dialog: a number and its unit (days when the hours are whole days)
function dw_row(key, label, h) {
  const d = h && !(h % 24);
  return `<div class="row dwrow"><label for="dw-${key}">${esc(label)}</label><input id="dw-${key}" type="number" min="0" max="8760" step="1" inputmode="numeric" value="${h ? (d ? h / 24 : h) : ''}" placeholder="${esc(tr('None'))}">
    <select id="dw-${key}-u" aria-label="${esc(tr('Unit'))}"><option value="1"${d ? '' : ' selected'}>${esc(tr('Hours'))}</option><option value="24"${d ? ' selected' : ''}>${esc(tr('Days'))}</option></select></div>`;
}
async function dw_setLim(sid) {
  const s = wip_sec(sid); if (!s) return;
  const v0 = {dwell_warn_h: s.dwell_warn_h ?? null, dwell_alert_h: s.dwell_alert_h ?? null};
  let md = null;
  const ok = await askDialog({title: tr('Time limits of {0}', s.name), ok: tr('Save'),
    html: `<p>${esc(tr('Each card shows how long it has been in this column. Above a limit the time turns yellow or red. Empty = no limit.'))}</p>${dw_row('warn', tr('Yellow after'), v0.dwell_warn_h)}${dw_row('alert', tr('Red after'), v0.dwell_alert_h)}`,
    after: m => { md = m; }});
  if (!ok || !md) return;
  const val = k => { const n = parseInt($(`#dw-${k}`, md).value, 10); return n > 0 ? Math.min(n * +$(`#dw-${k}-u`, md).value, 8760) : null; };
  const v = {dwell_warn_h: val('warn'), dwell_alert_h: val('alert')};
  if (v.dwell_warn_h && v.dwell_alert_h && v.dwell_alert_h <= v.dwell_warn_h) { toast(tr('The red limit must be above the yellow one.')); return; }
  if (v.dwell_warn_h === v0.dwell_warn_h && v.dwell_alert_h === v0.dwell_alert_h) return;
  try { await optWrite(optSet(() => wip_sec(sid), v), () => api('PATCH', '/api/sections/' + sid, v)); } catch { return; }
  const go = (to, from) => async e => {
    const r = await api('PATCH', '/api/sections/' + secId(e.sid), {...to, _prev: from});
    if (r.conflicts?.length) return {skipped: [tr('Section {0}', qn(s.name.slice(0, 40)))], none: true};
    const x = wip_sec(secId(e.sid)); if (x) Object.assign(x, to);
    return {};
  };
  offerUndo(tr('Time limits of {0} saved', qn(s.name.slice(0, 40))),
    histAdd({label: tr('Time limits of {0}', qn(s.name.slice(0, 40))), lids: [s.list_id], sid, undo: go(v0, v), redo: go(v, v0)}));
}
