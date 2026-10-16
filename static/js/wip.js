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

