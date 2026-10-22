// 2.39.1: the basket (#1219), the group headers of the views across lists (#1221) and the sidebar's "Fold all" (#1185).

// ---- #1185: the sidebar - one button folds / unfolds every group and folder at once (stored like a single fold)
// A person who had "Views" open before 2.39.1 finds "Areas" (the modules that were in "Views") open too
// 2.45.0 (#1502): "More" starts folded; a device that ran Kalmido before keeps it open unless every group was folded ("Fold all");
// an open "Tags" (S.collapsed side:tags-open) becomes an open group. Runs before the "Areas" step below, which marks a used device
(() => {
  if (LS.get('sbMoreMig', 0)) return;
  const o = new Set(LS.get('sideOpenG', []) || []), sg = LS.get('sideGroups', []) || [];
  if (LS.get('kbAreasMig', 0) && !['focus', 'lists', 'filters', 'team'].every(g => sg.includes(g))) o.add('more');
  if ((LS.get('collapsed', []) || []).includes('side:tags-open')) o.add('tags');
  LS.set('sideOpenG', [...o]); LS.set('sbMoreMig', 1);
})();
(() => { if (LS.get('kbAreasMig', 0)) return; const o = LS.get('sideOpenG', []) || []; if (o.includes('views') && !o.includes('areas')) LS.set('sideOpenG', [...o, 'areas']); LS.set('kbAreasMig', 1); })();
const kbSideGroups = () => sideGroupOrder().filter(g => !sideHidden('g:' + g) || g === 'lists');
const kbSideAnyOpen = () => kbSideGroups().some(g => sideOpen(g)) || folderNames().some(f => !foldClosed(f));  // 2.45.0 (#1502): Tags is a group now
function kbSideSetAll(closed) {
  if (sv_setAll(closed)) return;  // 2.156.0 D (#2186): in a sidebar view only for now
  for (const g of SIDE_GROUPS) {
    const key = SIDE_FOLDED.includes(g) ? 'sideOpenG' : 'sideGroups', x = new Set(LS.get(key, []) || []);
    if (SIDE_FOLDED.includes(g) === closed) x.delete(g); else x.add(g);
    LS.set(key, [...x]);
  }
  for (const f of folderNames()) if (foldClosed(f) !== closed) foldSet(f, closed);
  renderSide();
}
function kbFoldAllBtn() {
  const open = kbSideAnyOpen(), lab = open ? tr('Fold all') : tr('Unfold all');
  return `<button type="button" class="iconbtn kbfoldall" data-kb="side-all" aria-pressed="${!open}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic(open ? 'collapse' : 'expand', 's')}</button>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-kb="side-all"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); kbSideSetAll(kbSideAnyOpen());
}, true);

// ---- #1221: the group headers of the views across lists show where a group comes from (folder › list) and the groups can
// be put in an own order (per view, on every device: the user setting group_order); the default is the sidebar's order
const kbListOrder = () => { const a = [inbox(), ...sideOrder()].filter(Boolean), ids = new Set(a.map(l => l.id)); return [...a, ...S.lists.filter(l => !ids.has(l.id))]; };
function kbGroupPrefs() { try { const o = JSON.parse(S.settings?.group_order || '{}'); return o && typeof o === 'object' ? o : {}; } catch { return {}; } }
const kbGroupView = () => S.route.mod === 'tasks' && !S.route.key.startsWith('l:') && S.route.key !== 'inbox';
function kbOrderGroups(gs) {
  const own = kbGroupView() ? kbGroupPrefs()[S.route.key] : null;
  if (!Array.isArray(own) || !own.length) return gs;
  const at = id => { const i = own.indexOf(id); return i < 0 ? 1e6 : i; };  // new groups below
  return gs.map((g, i) => [g, i]).sort((x, y) => (x[0].lic ? at(x[0].id) : -1) - (y[0].lic ? at(y[0].id) : -1) || x[1] - y[1]).map(x => x[0]);
}
async function kbGroupSave(ids) {
  const o = kbGroupPrefs(); delete o[S.route.key]; if (ids && ids.length) o[S.route.key] = ids;  // #1334: the last saved view last (the server keeps the newest 40)
  S.settings.group_order = JSON.stringify(o);
  render();
  try { await api('PATCH', '/api/settings', {group_order: S.settings.group_order}); } catch { /* offline: the next save sends it */ }
}
const kbShownGroups = () => $$('#view .group[data-kbg]').map(x => x.dataset.kbg);
function kbGroupMove(id, to) {  // to: an index in the shown order
  const ids = kbShownGroups(), i = ids.indexOf(id); if (i < 0) return;
  ids.splice(i, 1); ids.splice(Math.max(0, Math.min(ids.length, to)), 0, id);
  kbGroupSave(ids);
}
function kbGroupMenu(anchor, id) {
  const ids = kbShownGroups(), i = ids.indexOf(id);
  // 2.62.0 (#1853): "Change position…" = one entry with the four moves in a second level
  menu(anchor, [mpo_posItem([{label: tr('Move up'), icon: 'up', dis: i <= 0, fn: () => kbGroupMove(id, i - 1)}, {label: tr('Move down'), icon: 'down', dis: i >= ids.length - 1, fn: () => kbGroupMove(id, i + 1)},
    {label: tr('To the top'), icon: 'up', dis: i <= 0, fn: () => kbGroupMove(id, 0)}, {label: tr('To the bottom'), icon: 'down', dis: i >= ids.length - 1, fn: () => kbGroupMove(id, ids.length)}]),
    ...(kbGroupPrefs()[S.route.key] ? ['-', kbGroupResetItem()] : [])], null, null, tr('Group order'));
}
const kbGroupResetItem = () => ({label: tr('Reset the order'), icon: 'sort', fn: () => { kbGroupSave(null); toast(tr('Groups in the sidebar’s order again')); }});
const kbGroupResetItems = () => kbGroupView() && kbGroupPrefs()[S.route.key] ? [kbGroupResetItem()] : [];
// the header's name of a list group: "Folder › Subfolder › List", the path grey, every part opens what it names
function kbCrumbHtml(g) {
  const l = g.lic; if (!l || !l.folder) return esc(g.name);
  const parts = [], f = l.folder;
  if (fParent(f)) parts.push([fParent(f), fParent(f)]);
  parts.push([f, fName(f)]);
  const shown = isMobile() ? parts.slice(-1) : parts;
  return `<span class="kbcrumb">${isMobile() && parts.length > 1 ? '<span class="kbcp" aria-hidden="true">…</span><span class="kbsep" aria-hidden="true">›</span>' : ''}${shown.map(([p, n]) => `<a class="kbcp" href="#${esc(keyToHash('folder:' + p))}" data-kbgo="${esc(keyToHash('folder:' + p))}">${esc(n)}</a><span class="kbsep" aria-hidden="true">›</span>`).join('')}<a class="kbcl" href="#${esc(keyToHash('l:' + l.id))}" data-kbgo="${esc(keyToHash('l:' + l.id))}">${esc(g.name)}</a></span>`;
}
// the grip (mouse: drag, a click opens the menu; touch: a long press on the header opens it)
const kbGrip = g => kbGroupView() && g.lic ? `<button type="button" class="iconbtn kbgrip" data-kb="grp-menu" data-g="${esc(g.id)}" ${isTouch() ? '' : 'draggable="true"'} title="${esc(tr('Drag to reorder'))}" aria-label="${esc(tr('Group order'))}: ${esc(g.name)}">${ic('grip', 's')}</button>` : '';
const kbGroupAttr = g => kbGroupView() && g.lic ? ` data-kbg="${esc(g.id)}"` : '';

document.addEventListener('click', e => {
  const c = e.target.closest?.('[data-kbgo]');
  if (c) { e.preventDefault(); e.stopPropagation(); go(c.dataset.kbgo); return; }
  const b = e.target.closest?.('[data-kb="grp-menu"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); kbGroupMenu(b, b.dataset.g);
}, true);
let kbDrag = null;
document.addEventListener('dragstart', e => {
  const g = e.target.closest?.('.kbgrip'); if (!g) return;
  e.stopPropagation(); kbDrag = g.dataset.g;
  try { e.dataTransfer.setData('text/plain', kbDrag); e.dataTransfer.effectAllowed = 'move'; } catch { /* old browsers */ }
  g.closest('.group')?.classList.add('kbdragging');
}, true);
document.addEventListener('dragover', e => { if (!kbDrag) return; const t = e.target.closest?.('.group[data-kbg]'); if (!t) return; e.preventDefault(); e.stopPropagation(); $$('#view .kbdrop').forEach(x => x.classList.remove('kbdrop')); t.classList.add('kbdrop'); }, true);
document.addEventListener('drop', e => {
  if (!kbDrag) return;
  const t = e.target.closest?.('.group[data-kbg]'); const id = kbDrag; kbDrag = null;
  if (!t) return;
  e.preventDefault(); e.stopPropagation();
  const ids = kbShownGroups(); kbGroupMove(id, ids.indexOf(t.dataset.kbg));
}, true);
document.addEventListener('dragend', () => { if (!kbDrag) return; kbDrag = null; $$('#view .kbdrop, #view .kbdragging').forEach(x => x.classList.remove('kbdrop', 'kbdragging')); }, true);
// touch: a long press on a list group's header opens the order menu
let kbLp = null;
document.addEventListener('touchstart', e => {
  const h = e.target.closest?.('.group[data-kbg] > .ghead'); if (!h || e.touches.length > 1) return;
  clearTimeout(kbLp);
  kbLp = setTimeout(() => { kbLp = 'fired'; kbGroupMenu(h, h.parentElement.dataset.kbg); }, 550);
}, {passive: true});
for (const ev of ['touchmove', 'touchcancel']) document.addEventListener(ev, () => { if (kbLp && kbLp !== 'fired') { clearTimeout(kbLp); kbLp = null; } }, {passive: true});
document.addEventListener('touchend', e => {
  if (!kbLp) return;
  if (kbLp === 'fired') e.preventDefault();  // no fold after the long press
  else clearTimeout(kbLp);
  kbLp = null;
}, {passive: false});

// ---- #1219: the basket
// the basket's number in the sidebar reads "to sort"
function kbInboxRowTip(h) {
  const n = kbBasketOpen().length; if (!n) return h;
  const t = esc(trn('{0} to sort', '{0} to sort', n));
  return h.replace(/<span class="c ([^"]*)">(\d+)<\/span>/, `<span class="c $1" title="${t}">$2<span class="sr"> ${esc(tr('to sort'))}</span></span>`);
}

// ---- #1219: "Sort" in the basket: one item after the other - to a list, to me, a date, waiting on someone, delete, skip
const KB = {ids: [], i: 0, md: null, n: 0, waitOpen: false};
// "to sort": an open item of the basket without a date, an assignee or someone it waits on (what it gets in the sort mode
// takes it out of the count, also when it stays in the basket)
const kbUnsorted = t => !t.parent_id && !t.context && t.status === 0 && !t.deleted_at && t.list_id === inbox()?.id && !t.due && !t.waiting_at && !t.assignee_id && !t.assignee_group_id;
const kbBasketOpen = () => openTasks().filter(kbUnsorted).sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id);
function kbSortBtn() {
  if (!inbox() || !kbBasketOpen().length) return '';
  return `<button type="button" class="btn sm tf kbsortb" data-kb="sort" data-ico="sort" title="${esc(tr('Sort the basket item by item'))}">${ic('sort', 's')}<span class="bl">${tr('Sort|basket')}</span></button>`;
}
const KB_ACTS = [['list', '1', 'list', N_('To a project')], ['me', '2', 'user', N_('Assign to me')], ['today', '3', 'sun', N_('Today')], ['tomorrow', '4', 'sunrise', N_('Tomorrow')],
  ['date', '5', 'cal', N_('Date…')], ['wait', '6', 'hourglass', N_('Waiting on someone')], ['del', '7', 'trash', N_('Delete')], ['skip', '0', 'right', N_('Skip')]];
const kbActOn = a => a !== 'me' || (collab() && !!S.me);
function kbSortStart() {
  KB.ids = kbBasketOpen().map(t => t.id); KB.i = 0; KB.n = 0; KB.waitOpen = false;
  if (!KB.ids.length) { toast(tr('The basket is empty')); return; }
  KB.md = modal('<div class="kbsort" tabindex="-1"></div>');
  KB.md.classList.add('kbsortm');
  KB.md.addEventListener('click', kbSortClick);
  KB.md.addEventListener('keydown', kbSortKey);
  onRemove(KB.md, () => { KB.md = null; try { render(); } catch { /* the page is gone */ } });
  kbSortDraw();
}
const kbCur = () => { while (KB.i < KB.ids.length) { const t = taskById(KB.ids[KB.i]); if (t && kbUnsorted(t)) return t; KB.i++; } return null; };
function kbSortDraw() {
  const box = KB.md && $('.kbsort', KB.md); if (!box) return;
  const t = kbCur();
  if (!t) {
    const left = kbBasketOpen().length;
    box.innerHTML = `<div class="kbend">${botEmpty('erledigt', left ? tr('Done for now') : tr('Basket empty'), left ? trn('{0} item is still to sort.', '{0} items are still to sort.', left) : tr('Everything is sorted.'))}</div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-kbs="end">${tr('Close')}</button></div>`;
    $('[data-kbs="end"]', box)?.focus();
    return;
  }
  const n = KB.ids.length, pos = Math.min(KB.i + 1, n);
  const acts = KB_ACTS.filter(([a]) => kbActOn(a)).map(([a, k, i, lab]) => `<button type="button" class="btn kbact kba-${a}" data-kbs="${a}" aria-keyshortcuts="${k}"><kbd aria-hidden="true">${k}</kbd>${ic(i, 's')}<span>${esc(tr(lab))}</span></button>`).join('');
  box.innerHTML = `<div class="kbhead"><h3>${ic('inbox', 's')} ${tr('Sort the basket')}</h3><span class="kbpos">${esc(tr('{0} of {1}', pos, n))}</span><button type="button" class="iconbtn" data-kbs="end" title="${esc(tr('End (Esc)'))}" aria-label="${esc(tr('End (Esc)'))}">${ic('x', 's')}</button></div>
    <div class="kbtask"><b class="kbttl">${mdTitleNL(t.title)}</b>${t.notes ? `<p class="kbnotes muted">${esc(String(t.notes).slice(0, 280))}</p>` : ''}${t.due ? `<span class="muted">${esc(tr('Date: {0}', dayLabel(t.due)))}</span>` : ''}</div>
    ${KB.waitOpen ? `<div class="kbwait"><label for="kb-wn">${tr('Waiting on')}</label><input id="kb-wn" maxlength="300" placeholder="${esc(tr('who or what, e.g. offer from the carpenter'))}" enterkeyhint="done"><button type="button" class="btn pri" data-kbs="wait-ok">${tr('OK')}</button></div>` : ''}
    <div class="kbacts" role="group" aria-label="${esc(tr('Sort the basket'))}">${acts}</div>
    ${isTouch() ? '' : `<div class="kbleg muted">${esc(tr('Keys: the numbers on the buttons, Esc ends'))}</div>`}`;
  if (KB.waitOpen) $('#kb-wn', box)?.focus(); else box.focus?.();
}
function kbNext(done = true) { if (done) KB.n++; KB.i++; KB.waitOpen = false; kbSortDraw(); }
async function kbSortDo(a, anchor) {
  const t = kbCur(); if (!t) { if (a === 'end') KB.md?.remove(); return; }
  if (a === 'end') { KB.md?.remove(); return; }
  if (a === 'skip') { kbNext(false); return; }
  if (a === 'list') {
    tch_listPicker(anchor || $('[data-kbs="list"]', KB.md), {filter: l => !l.is_inbox && canAddTo(l.id), pick: async l => { await patchUndoable(t.id, {list_id: l.id}, tr('Moved to {0}', lname(l))); kbNext(); }});
    return;
  }
  if (a === 'me') { await patchUndoable(t.id, {assignee_id: S.me.id}, tr('Assigned to me')); kbNext(); return; }
  if (a === 'today' || a === 'tomorrow') { const d = addDays(today(), a === 'today' ? 0 : 1); await patchUndoable(t.id, {due: d}, tr('Due: {0}', dayLabel(d))); kbNext(); return; }
  if (a === 'date') {  // the date popover; when it closes with a date set, the next item comes
    const due0 = t.due, pop = $('#pop');
    datePop(anchor || $('[data-kbs="date"]', KB.md), t.id);
    if (!pop) return;
    const mo = new MutationObserver(() => { if (!pop.classList.contains('hidden')) return; mo.disconnect(); setTimeout(() => { const x = taskById(t.id); if (x && x.due !== due0) kbNext(); else kbSortDraw(); }, 400); });
    mo.observe(pop, {attributes: true, attributeFilter: ['class']});
    return;
  }
  if (a === 'wait') { KB.waitOpen = true; kbSortDraw(); return; }
  if (a === 'wait-ok') {
    const note = ($('#kb-wn', KB.md)?.value || '').trim(), body = {note, until: addDays(today(), 7)};
    try { putTask(await api('PUT', `/api/tasks/${t.id}/waiting`, body)); } catch { return; }
    toast(tr('Waiting on someone'), async () => { putTask(await api('DELETE', `/api/tasks/${t.id}/waiting`)); render(); });
    kbNext(); return;
  }
  if (a === 'del') { await deleteTask(t.id); kbNext(); }
}
function kbSortClick(e) {
  const b = e.target.closest('[data-kbs]'); if (!b) return;
  e.preventDefault(); kbSortDo(b.dataset.kbs, b);
}
function kbSortKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || !KB.md) return;
  if (!$('#pop')?.classList.contains('hidden') && $('#pop')) return;  // a list menu / the date popover has the keys
  if (e.target.id === 'kb-wn') { if (e.key === 'Enter') { e.preventDefault(); kbSortDo('wait-ok'); } return; }
  const a = e.key === 'ArrowRight' ? 'skip' : e.key === 'Delete' ? 'del' : (KB_ACTS.find(x => x[1] === e.key && kbActOn(x[0])) || [])[0];
  if (!a || !kbCur()) return;
  e.preventDefault(); e.stopPropagation();
  kbSortDo(a, $(`[data-kbs="${a}"]`, KB.md));
}

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-kb="sort"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); kbSortStart();
}, true);

// ---- #1219: "My tasks" also shows the open, unassigned tasks without a date from lists only I use (one foldable group at the end)
const kbSoloList = l => !!l && !l.is_inbox && !l.archived && l.role === 'owner' && !l.shared && !(l.shared_agents || []).length;
function kbMineGroup() {
  if (S.route.key !== 'assigned') return null;
  const ts = openTasks(true).filter(t => !t.parent_id && !t.context && t.status === 0 && !t.deleted_at && !t.due && !t.assignee_id && !t.assignee_group_id && kbSoloList(listById(t.list_id)));
  if (!ts.length) return null;
  const ord = kbListOrder().map(l => l.id);
  ts.sort((a, b) => ord.indexOf(a.list_id) - ord.indexOf(b.list_id) || (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id);
  return {id: 'kb:mine', name: tr('From your projects, without a date'), tasks: ts, cls: 'kbmine'};
}

