// 2.56.1 (#1799): fewer symbols in the task row and the sidebar, per person on every device (Settings > Appearance).
// Task rows: a level (all | key | calm | custom, default key) in row_icons, the switched-on symbols of "Custom" in
// row_icons_custom (comma list of the keys below; '' = not chosen yet = the "Important" set, 'none' = none).
// THE one table of every row symbol: [key, group, label, shown by "Important"]. "Calm" = only the due date, "All" = every one.
// Always shown, whatever the level: the status circle (+ its priority mark), red (overdue), an agent waiting for your yes
// (approval chips), the read-only context mark, the trash marks and a list's own columns (opts.lc). The task view
// (detail) and the board cards are not touched: they still show everything.
const RSY_SYMS = [
  ['due', 'dates', N_('Due'), 1], ['repeat', 'dates', N_('Repeat'), 0], ['remind', 'dates', N_('Reminder'), 1], ['deadline', 'dates', N_('Deadline'), 1],
  ['occ', 'dates', N_('Occasion|rowsym'), 0],  // a birthday / anniversary of the family module
  ['note', 'content', N_('Note'), 0], ['attach', 'content', N_('Attachments'), 0], ['link', 'content', N_('Link'), 0], ['sub', 'content', N_('Subtasks'), 0],
  ['cmt', 'content', N_('Comments'), 0], ['code', 'content', N_('Code changes|rowsym'), 0],
  ['tracked', 'time', N_('Tracked'), 0], ['plan', 'time', N_('Planned time'), 0],
  ['ttype', 'status', N_('Ticket type'), 0], ['ms', 'status', N_('Milestone'), 0],
  ['blocked', 'status', N_('Blocked or locked|rowsym'), 1],  // blocked by another task, "Ready to start", the title lock
  ['wait', 'status', N_('Waiting'), 0], ['stale', 'status', N_('Lying idle|rowsym'), 0], ['pin', 'status', N_('Pinned'), 0],
  ['list', 'place', N_('Project'), 0], ['tags', 'place', N_('Tags'), 0], ['fields', 'place', N_('Pinned fields|rowsym'), 0], ['created', 'place', N_('Created'), 0],
  ['num', 'place', N_('Ticket number'), 0],
  ['person', 'people', N_('Person or group|rowsym'), 1], ['turns', 'people', N_('Takes turns'), 1]];
const RSY_GROUPS = [['dates', N_('Dates|rowsym')], ['content', N_('Content|rowsym')], ['time', N_('Time|rowsym')], ['status', N_('Status')], ['place', N_('Placement|rowsym')], ['people', N_('People')]];
const RSY_LEVELS = [['all', N_('All|rowsym')], ['key', N_('Important|rowsym')], ['calm', N_('Calm|rowsym')], ['custom', N_('Custom|rowsym')]];
const rsy_level = () => RSY_LEVELS.some(([v]) => v === S.settings?.row_icons) ? S.settings.row_icons : 'key';
const rsy_keySet = () => RSY_SYMS.filter(x => x[3]).map(x => x[0]);
let rsy_memo = ['', null];  // [level|custom, Set]: taskRow asks for every symbol of every row
function rsy_set() {
  const lv = rsy_level(), cu = S.settings?.row_icons_custom || '', sig = lv + '|' + cu;
  if (rsy_memo[0] === sig && rsy_memo[1]) return rsy_memo[1];
  const keys = lv === 'all' ? RSY_SYMS.map(x => x[0]) : lv === 'calm' ? ['due'] : lv === 'key' || !cu ? rsy_keySet() : cu.split(',');
  rsy_memo = [sig, new Set(keys)];
  return rsy_memo[1];
}
const rsy_on = k => rsy_set().has(k);
// the sidebar: task counts, the status dots of lists, the share marks (person / robot); default on
const rsy_sideCnt = () => S.settings?.side_count !== '0';
const rsy_sideDot = () => S.settings?.side_dots !== '0';
const rsy_sideShr = () => S.settings?.side_share !== '0';

// the live preview in Settings > Appearance (lookHtml): the meta line of preview row i under the chosen level
function rsy_pv(i) {
  const m = i ? [['due', `<span class="dt">${ic('cal', 's')}${dayLabel(addDays(today(), 3))}</span>`], ['sub', `<span class="subc">${ic('sub', 's')}1/3</span>`], ['attach', `<span>${ic('clip', 's')}2</span>`], ['tracked', `<span class="tchip">${ic('clock', 's')}<b>0:45</b></span>`]]
    : [['due', `<span class="dt today">${ic('cal', 's')}${tr('Today')} 09:30</span>`], ['remind', `<span>${ic('bell', 's')}</span>`], ['note', `<span>${ic('edit', 's')}</span>`], ['tags', `<span class="tag">#${tr('home')}</span>`]];
  return m.filter(([k]) => rsy_on(k)).map(([, h]) => h).join('');
}

// Settings > Appearance > Task rows: the level as a segment, "Custom" opens the boxes per group
function rsy_setHtml() {
  const lv = rsy_level(), on = rsy_set();
  const seg = `<div class="seg wrap rsy-seg" role="group" aria-labelledby="rsy-h">${RSY_LEVELS.map(([v, n]) => `<button type="button" data-rsy-lv="${v}" aria-pressed="${lv === v}" class="${lv === v ? 'on' : ''}">${tr(n)}</button>`).join('')}</div>`;
  const grps = lv !== 'custom' ? '' : `<div class="rsy-grps">${RSY_GROUPS.map(([g, gn]) => `<fieldset class="rsy-g"><legend>${tr(gn)}</legend>${RSY_SYMS.filter(x => x[1] === g).map(([k, , n]) =>
    `<label class="chkl"><input type="checkbox" data-rsy="${k}" ${on.has(k) ? 'checked' : ''}> ${tr(n)}</label>`).join('')}</fieldset>`).join('')}</div>`;
  return `<div id="rsy-set"><div class="row rsy-row"><span class="rsy-l" id="rsy-h">${tr('Symbols in the row')}</span>${seg}</div>${grps}
    <div class="shint">${tr('All: every symbol as before. Important: due date, reminder, person, approvals and locks. Calm: only the title, the status circle and the due date. Overdue tasks, an agent waiting for your yes and the status circle always show; the task itself shows everything. For all your devices.')}</div></div>`;
}
function rsy_sideSetHtml(chk) {  // the three sidebar switches (SETS s-sidecnt / s-sidedot / s-sideshr)
  const s = S.settings || {};
  return `<div class="row">${chk('s-sidecnt', s.side_count !== '0', tr('Task counts in the sidebar'))}</div>
    <div class="row">${chk('s-sidedot', s.side_dots !== '0', tr('Status dots of projects'))}</div>
    ${collab() ? `<div class="row">${chk('s-sideshr', s.side_share !== '0', tr('Share marks (person / robot)'))}</div>` : ''}
    <div class="shint">${tr('Without counts, Today keeps its red number while something is overdue.')}</div>`;
}
function rsy_sync(md) {  // after an undo / redo / a change on another device: the controls and the preview follow
  const b = $('#rsy-set', md); if (!b) return;
  const f = document.activeElement, fk = f && b.contains(f) ? (f.dataset.rsyLv ? `[data-rsy-lv="${f.dataset.rsyLv}"]` : f.dataset.rsy ? `[data-rsy="${f.dataset.rsy}"]` : '') : '';
  b.outerHTML = rsy_setHtml();
  if (fk) $('#rsy-set ' + fk, md)?.focus();
  const lk = $('#s-lookin', md); if (lk) lk.innerHTML = lookHtml();
}
async function rsy_save(patch) {  // one undo step; the rows redraw at once (row_icons* are in SET_RENDER)
  const md = $$('.smodal').pop();
  const p = setApply(patch, tr('Symbols in the row'));
  if (md) rsy_sync(md);  // the value counts at once (optSet), the request runs; an error puts it back (settingsSync)
  await p;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('#rsy-set [data-rsy-lv]'); if (!b) return;
  const lv = b.dataset.rsyLv; if (lv === rsy_level()) return;
  const patch = {row_icons: lv};
  // "Custom" the first time: it starts from what the row shows now
  if (lv === 'custom' && !S.settings?.row_icons_custom) patch.row_icons_custom = [...rsy_set()].join(',') || 'none';
  rsy_save(patch);
});
document.addEventListener('change', e => {
  const el = e.target; if (!el.matches?.('#rsy-set [data-rsy]')) return;
  const on = new Set(rsy_set());
  el.checked ? on.add(el.dataset.rsy) : on.delete(el.dataset.rsy);
  rsy_save({row_icons_custom: RSY_SYMS.map(x => x[0]).filter(k => on.has(k)).join(',') || 'none'});
});
