// @ts-check
/* Kalmido web client: Kanban swimlanes.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';
// 2.138.0 D (#2060, #2033): the board of a list grouped into horizontal lanes by person (assignee), priority or a custom
// field (select / checkbox). One button above the board picks it, remembered per person (localStorage is per account) and
// list; none = the board as before. The column heads (WIP limit, sums, rename, drag) stay in one row on top, each lane
// has its head (name, count, fold) and the same columns below. Dropping a card into another lane sets that lane's value
// through the normal task route (one undo step with the column move, write right needed); "+ Task" in a lane creates the
// task with the lane's value. The whole board scrolls sideways as one, so the columns stay aligned.
const SWL_FT = ['select', 'checkbox'];
const swlAll = () => LS.get('swl', {});
const swlFields = lid => fieldsOf(lid).filter(f => SWL_FT.includes(f.type));
// the stored choice of list lid, if it still applies ('' = no lanes, 'prio', 'person', 'f<field id>')
function swlMode(lid) {
  const m = String(swlAll()[lid] || '');
  if (m === 'prio') return m;
  if (m === 'person') return collab() ? m : '';
  if (/^f\d+$/.test(m)) return swlFields(lid).some(f => f.id === +m.slice(1)) ? m : '';
  return '';
}
function swlSet(lid, m) {
  const a = swlAll();
  if (m) a[lid] = m; else delete a[lid];
  LS.set('swl', a); renderView();
}
const swlModeName = (lid, m) => m === 'prio' ? tr('Priority') : m === 'person' ? tr('Person') : m ? fieldById(+m.slice(1))?.name || '' : tr('None');
// the lanes: [{key, name, has(task)}], the lane without a value last. Priority: all four; person: the people (and groups)
// with tasks on the board; a field: its options (checkbox: yes / no)
function swlLanes(lid, m, tasks) {
  if (m === 'prio') return [5, 3, 1, 0].map(p => ({key: 'p' + p, name: p ? tr(PRIO_NAMES[p]) : tr('No priority'), cls: 'flag-' + p, has: t => (t.priority || 0) === p}));
  if (m === 'person') {
    const us = new Set(), gs = new Set();
    for (const t of tasks) { if (t.assignee_id) us.add(t.assignee_id); else if (t.assignee_group_id) gs.add(t.assignee_group_id); }
    const by = (a, b) => a.name.localeCompare(b.name, LOCALE());
    return [...[...us].map(u => ({key: 'u' + u, name: personName(lid, u) || personNameAny(u) || '?', uid: u, has: t => t.assignee_id === u})).sort(by),
      ...[...gs].map(g => ({key: 'g' + g, name: (listGroups(lid).find(x => x.group_id === g)?.name || '?') + ' · ' + tr('Group'), has: t => !t.assignee_id && t.assignee_group_id === g})).sort(by),
      {key: 'n', name: tr('Nobody assigned'), has: t => !t.assignee_id && !t.assignee_group_id}];
  }
  const f = m ? fieldById(+m.slice(1)) : null; if (!f) return [];
  const v = t => String(t.fields?.[f.id] ?? '');
  if (f.type === 'checkbox') return [{key: 'v1', name: f.name + ': ' + tr('yes'), has: t => v(t) === '1'}, {key: 'n', name: f.name + ': ' + tr('no'), has: t => v(t) !== '1'}];
  const os = f.options?.options || [];
  return [...os.map(o => ({key: 'v' + o.id, name: o.name, opt: o, has: t => v(t) === String(o.id)})), {key: 'n', name: tr('No value'), has: t => !os.some(o => v(t) === String(o.id))}];
}
// the button above the board
function swlBar(lid) {
  const m = swlMode(lid), lab = tr('Swimlanes') + ': ' + swlModeName(lid, m);
  return `<div class="swlbar"><button type="button" class="btn sm swlbtn${m ? ' on' : ''}" data-swl-menu="${lid}" aria-haspopup="menu" title="${esc(lab)}">${ic('menu', 's')}<span>${esc(lab)}</span></button></div>`;
}
function swlMenu(anchor, lid) {
  const m = swlMode(lid);
  menu(anchor, [{head: tr('Swimlanes')}, {label: tr('None'), icon: 'x', on: !m, fn: () => swlSet(lid, '')},
    ...(collab() ? [{label: tr('Person'), icon: 'user', on: m === 'person', fn: () => swlSet(lid, 'person')}] : []),
    {label: tr('Priority'), icon: 'flag', on: m === 'prio', fn: () => swlSet(lid, 'prio')},
    ...swlFields(lid).map(f => ({label: f.name, icon: f.type === 'checkbox' ? 'check' : 'list', on: m === 'f' + f.id, fn: () => swlSet(lid, 'f' + f.id)}))]);
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('#view [data-swl-menu]'); if (!b) return;
  swlMenu(b, +b.dataset.swlMenu);
});
// the board with lanes; o = the column parts of viewKanban (head, add, knew), so both boards draw a column the same way
function swlBoard(lid, m, cols, tasks, o) {
  const lanes = swlLanes(lid, m, tasks);
  const top = `<div class="swlrow swlhrow">${cols.map(c => `<div class="kcol swlhc" data-kcol="${c.id ?? ''}">${o.head(c)}</div>`).join('')}${o.knew}</div>`;
  return `<div class="kanban swl" data-swlmode="${esc(m)}">${top}${lanes.map(L => {
    const per = cols.map(c => c.tasks.filter(L.has)), n = per.reduce((a, x) => a + x.length, 0), k = `swl:${lid}:${m}:${L.key}`, closed = S.collapsed.has(k);
    const dot = L.opt ? `<i class="swldot" ${lrSelStyle(L.opt)}></i>` : L.uid ? av(L.uid, L.name, 'avatar swlav') : L.cls ? `<span class="${L.cls}">${ic('flag', 's')}</span>` : '';
    return `<section class="swlane${closed ? ' closed' : ''}" data-swl="${esc(L.key)}" aria-label="${esc(L.name)}">
      <button type="button" class="swlh" data-act="collapse" data-key="${esc(k)}" aria-expanded="${!closed}">${ic('chev', 's')}${dot}<span class="swln">${esc(L.name)}</span><span class="c">${n}</span></button>
      ${closed ? '' : `<div class="swlrow">${cols.map((c, i) => `<div class="kcol swlc" data-kcol="${c.id ?? ''}"><div class="kcards">${per[i].map(t => taskRow(t, {compact: true, dwell: lid})).join('')}</div>${o.add(c, L.key, L.name)}</div>`).join('')}</div>`}
    </section>`;
  }).join('')}</div>`;
}
// the values a lane stands for, as a task body (null = no lanes / unknown lane)
function swlBody(lid, key) {
  const m = swlMode(lid); if (!m || key == null) return null;
  if (m === 'prio') return {priority: +key.slice(1) || 0};
  if (m === 'person') return key[0] === 'u' ? {assignee_id: +key.slice(1)} : key[0] === 'g' ? {assignee_group_id: +key.slice(1)} : {assignee_id: null, assignee_group_id: null};
  const f = fieldById(+m.slice(1)); if (!f) return null;
  if (key === 'n') return {fields: {[f.id]: null}};
  const v = f.type === 'checkbox' ? '1' : (f.options?.options || []).find(o => 'v' + o.id === key)?.id;
  return v == null ? null : {fields: {[f.id]: v}};
}
// the part of body b that changes task t (a person replaces a group and the other way round)
function swlDiff(t, b) {
  const o = {};
  if ('priority' in b && (t.priority || 0) !== b.priority) o.priority = b.priority;
  if ('assignee_id' in b || 'assignee_group_id' in b) {
    const u = b.assignee_id || null, g = b.assignee_group_id || null;
    if (u !== (t.assignee_id || null)) o.assignee_id = u;
    if (g !== (t.assignee_group_id || null)) o.assignee_group_id = g;
  }
  if (b.fields) for (const [k, v] of Object.entries(b.fields)) if (String(t.fields?.[k] ?? '') !== String(v ?? '')) o.fields = {...o.fields, [k]: v};
  return Object.keys(o).length ? o : null;
}
// a drop into a lane (dnd.js dropTask, before the column move; the same history group): sets the lane's value.
// false = stopped (no write right, locked, the request failed): the column move does not happen either
async function swlDrop(id, el) {
  const ln = el?.closest?.('#view .kanban.swl .swlane[data-swl]'), t = S.tasks.get(id);
  if (!ln || !t || !el.closest('.kcol')) return true;
  const lid = routeList()?.id, b = lid && swlBody(lid, ln.dataset.swl), o = b && swlDiff(t, b);
  if (!o) return true;
  if (!(o.fields || 'priority' in o ? canEdit(t) : canAssign(t))) { roToast(); return false; }
  if (tlkHits(t, o)) { tlkToast(t); render(); return false; }
  try { await patchUndoable(id, o, tr('Swimlane: {0}', ln.getAttribute('aria-label') || '')); } catch { return false; }
  if (o.assignee_id && typeof ab2_warnAssign === 'function') ab2_warnAssign(o.assignee_id, S.tasks.get(id) || t);  // as the assign menu: warn when away
  return true;
}
// "+ Task" in a lane: the lane's value for the new task (a priority typed with "!" wins)
function swlNew(lid, key, r) {
  const b = swlBody(lid, key); if (!b) return {};
  const o = {};
  if (b.priority && !r.priority) o.priority = b.priority;
  if (b.assignee_id && canEditList(lid)) o.assignee_id = b.assignee_id;
  if (b.assignee_group_id && canEditList(lid)) o.assignee_group_id = b.assignee_group_id;
  if (b.fields) { const [k, v] = Object.entries(b.fields)[0]; if (v != null) o.fields = {[k]: v}; }
  return o;
}
// a touch drop beside the cards: the columns of the lane row under the finger (dnd.js kbColAt); null = no lanes
function swlColsAt(y) {
  const rows = $$('#view .kanban.swl .swlrow'); if (!rows.length || y == null) return null;
  let best = null, bd = Infinity;
  for (const r of rows) { const b = r.getBoundingClientRect(), d = y < b.top ? b.top - y : y > b.bottom ? y - b.bottom : 0; if (d < bd) { bd = d; best = r; } }
  return best ? [...best.children].filter(c => c.classList.contains('kcol')) : null;
}
