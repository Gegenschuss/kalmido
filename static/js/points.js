'use strict';
// 2.60.0 B (#1511): story points of tasks (tasks.points 1 2 3 5 8 13, shown where the list has them on: lists.points_on)
// and the velocity of a list's last closed sprints (GET /api/lists/<id>/velocity). Each change is one undo step.
const SPT_VALUES = [1, 2, 3, 5, 8, 13];
const spt_on = lid => !!listById(lid)?.points_on;
function spt_sprintsOn(l) {
  const c = l?.sprint_cfg; if (!c) return false;
  if (typeof c === 'object') return !!c.on;
  try { return !!JSON.parse(c).on; } catch { return false; }
}
const spt_offer = l => !!l && !l.is_inbox && (!!l.tickets || spt_sprintsOn(l) || !!l.points_on);  // where the list dialog offers the switch
const spt_sum = ts => ts.reduce((a, t) => a + (t.points || 0), 0);
UNDO_FIELDS.push('points');  // a change of the points is undone like the other task fields
HIST_FIELDS.push('points');
FIELD_NAMES.points = N_('Story points');

// the points of a kanban column (next to its count), when the list has them on
const spt_kSum = (c, lid) => spt_on(lid) ? `<span class="c sptsum" title="${esc(tr('Story points'))}">${esc(tr('{0} pts', spt_sum(c.tasks)))}</span>` : '';
// ---- story points: the task row, the task panel, the multi panel
const spt_chip = t => t.points && spt_on(t.list_id) ? `<span class="sptm" title="${esc(tr('Story points: {0}', t.points))}"><span class="sr">${esc(tr('Story points'))} </span>${t.points}</span>` : '';
function spt_detailHtml(t, ro) {
  if (!spt_on(t.list_id) || isMs(t)) return '';
  return `<label for="d-spt">${tr('Story points')}</label><select id="d-spt" data-sheet-ico="hash" ${ro ? 'disabled' : ''}><option value="">${tr('None')}</option>${SPT_VALUES.map(v => `<option value="${v}" ${t.points === v ? 'selected' : ''}>${v}</option>`).join('')}</select>`;
}
document.addEventListener('change', e => {
  if (e.target.id !== 'd-spt' || !S.sel) return;
  const v = e.target.value ? +e.target.value : null;
  patchUndoable(S.sel, {points: v}, v ? tr('Story points: {0}', v) : tr('Story points removed'));
});
function spt_meField(ts) {
  if (!ts.length || !ts.every(t => spt_on(t.list_id))) return [];
  const set = v => meApply('points', t => (t.points || null) !== v ? {points: v} : null, tr('Story points'));
  return [{k: 'points', lab: N_('Story points'), icon: 'chart', get: t => t.points || 0, text: v => v ? String(v) : tr('None'),
    open: a => menu(a, [{label: tr('None'), icon: 'x', fn: () => set(null)}, '-', ...SPT_VALUES.map(v => ({label: String(v), fn: () => set(v)}))])}];
}

// ---- the list dialog: "Story points" (owner; lists with ticket types or sprints). Saved at once, one undo step
function spt_listRow(l, own) {
  if (!own || !l.id || l.is_inbox) return '';
  return `<div class="row sptrow" ${spt_offer(l) ? '' : 'hidden'}><label>${tr('Story points')}</label><label class="chkl"><input type="checkbox" id="l-spt" data-lid="${l.id}" ${l.points_on ? 'checked' : ''}> ${tr('Estimate tasks in points (1, 2, 3, 5, 8, 13)')}</label></div>`;
}
document.addEventListener('change', async e => {
  if (e.target.id === 'l-tickets') { const r = document.querySelector('.sptrow'); if (r && e.target.checked) r.hidden = false; return; }
  if (e.target.id !== 'l-spt') return;
  const lid = +e.target.dataset.lid, l = listById(lid); if (!l) return;
  const on = e.target.checked, nm = qn(lname(l).slice(0, 40));
  const put = async (to, from) => {
    const r = await api('PATCH', '/api/lists/' + lid, {points_on: to, _prev: {points_on: from}});
    if (r?.conflicts?.length) return {skipped: [nm], none: true};
    const x = listById(lid); if (x) x.points_on = to ? 1 : 0;
    render(); return {};
  };
  try { await api('PATCH', '/api/lists/' + lid, {points_on: on}); } catch { e.target.checked = !on; return; }
  l.points_on = on ? 1 : 0; render();
  offerUndo(on ? tr('Story points on in {0}', nm) : tr('Story points off in {0}', nm),
    histAdd({label: tr('Story points in {0}', nm), lids: [lid], undo: () => put(on ? 0 : 1, on ? 1 : 0), redo: () => put(on ? 1 : 0, on ? 0 : 1)}));
});

// ---- velocity: completed points of the last closed sprints (bars) and their average as a planning aid
const SPT_V = {};
async function spt_velLoad(lid) {
  const d = SPT_V[lid] || (SPT_V[lid] = {});
  if (d.busy || (d.j && d.v === S.v)) return;
  d.busy = true;
  try { d.j = await rawFetch('GET', `/api/lists/${lid}/velocity`); d.v = S.v; }
  catch { d.v = S.v; }
  finally { d.busy = false; }
  if (routeList()?.id === lid) viewSafeRender();
}
// the chart (SVG, one accent colour, every value also as text); '' while loading or without a closed sprint
function spt_velocityHtml(lid) {
  const d = SPT_V[lid];
  if (!d || (!d.busy && d.v !== S.v)) setTimeout(() => spt_velLoad(lid), 0);
  const j = d?.j; if (!j?.sprints?.length) return '';
  const sp = j.sprints, max = Math.max(1, ...sp.map(s => s.points)), W = 36, G = 12, H = 72, w = sp.length * (W + G) - G;
  const y = v => H - Math.round(v / max * (H - 4)), avg = j.average ?? 0;
  const bars = sp.map((s, i) => { const x = i * (W + G), nm = s.name || tr('Sprint {0}', s.num);
    return `<g><title>${esc(tr('{0}: {1} points, {2} tasks', nm, s.points, s.count))}</title><rect x="${x}" y="${y(s.points)}" width="${W}" height="${H - y(s.points)}" rx="3" class="sptbar"/>
      <text x="${x + W / 2}" y="${Math.max(10, y(s.points) - 4)}" class="sptval">${s.points}</text><text x="${x + W / 2}" y="${H + 14}" class="sptlab">${esc(String(s.num))}</text></g>`; }).join('');
  return `<div class="sptvel"><svg viewBox="0 -2 ${w} ${H + 18}" width="${w}" height="${H + 18}" role="img" aria-label="${esc(tr('Velocity: completed points of the last {0} sprints, average {1}', sp.length, avg))}">${bars}
    <line x1="0" x2="${w}" y1="${y(avg)}" y2="${y(avg)}" class="sptavg"/></svg>
    <p class="sptavgt">${esc(tr('Planning aid: avg. {0} points per sprint', avg))}</p></div>`;
}
// the block "Velocity" of the project page and its editor: only in lists with sprints and story points on (undefined = not offered)
const spt_povOn = l => !!l?.points_on && spt_sprintsOn(l);
{ const blocks = LY.project.blocks; LY.project.blocks = () => [...blocks(), ...(spt_povOn(routeList()) ? [['velocity', N_('Velocity'), 'chart', 'half']] : [])]; }
function spt_povPart(l) {
  if (!spt_povOn(l)) return undefined;
  const h = spt_velocityHtml(l.id);
  return x => povSec('velocity', tr('Velocity'), h, x, h ? '' : tr('Shows the completed points once the first sprint is closed.'));
}
