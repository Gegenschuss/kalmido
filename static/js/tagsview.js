/* Kalmido web client: tags overview (2.53.0, #446). Classic script sharing the global scope (load order: index.html).
   #tags = every tag of mine as a card; a card opens the filtered tag view (#tag/<name>). Data comes from the client state. */
'use strict';

// 2.53.0 (#446): one record per tag from S.tasks (open + the completed ones the client holds)
function tg_collect() {
  const m = new Map(), t0 = today();
  for (const t of S.tasks.values()) {
    if (t.deleted_at || t.context || archHidden(t) || wsHidden(t) || ovHidden(t)) continue;
    for (const g of t.tags || []) {
      let r = m.get(g);
      if (!r) m.set(g, r = {name: g, open: 0, done: 0, due: '', lists: new Map(), used: '', color: ''});
      if (t.status === 0) { r.open++; if (t.due && (!r.due || t.due < r.due)) r.due = t.due; } else r.done++;
      const l = listById(t.list_id); if (l) r.lists.set(l.id, lname(l));
      const u = t.updated_at || t.created_at || ''; if (u > r.used) r.used = u;
      const lc = cssColor(ltagColor(g, t.list_id)); if (lc && !r.color) r.color = lc;
    }
  }
  return [...m.values()].sort((a, b) => b.open - a.open || a.name.localeCompare(b.name, 'de')).map(r => ({...r, over: !!r.due && r.due < t0}));
}
function tg_card(r) {
  const ls = [...r.lists.values()], shown = ls.slice(0, 3).map(esc).join(' · ') + (ls.length > 3 ? ` +${ls.length - 3}` : '');
  const due = r.due ? `<span class="tgdue ${r.over ? 'over' : ''}">${ic('cal', 's')}${esc(r.over ? tr('Overdue since {0}', fmtDateLoc(r.due)) : tr('Next due {0}', fmtDateLoc(r.due)))}</span>` : '';
  return `<button type="button" class="tgcard" data-go="tag/${encodeURIComponent(r.name)}" ${r.color ? `style="--tc:${cssColor(r.color)}"` : ''} aria-label="${esc(tr('Open tag {0}', '#' + r.name))}">
    <span class="tgtop"><span class="tgdot"></span><b>#${esc(r.name)}</b></span>
    <span class="tgnum"><span><b>${r.open}</b> ${esc(tr('open'))}</span><span><b>${r.done}</b> ${esc(tr('done'))}</span></span>
    ${due}${ls.length ? `<span class="tglists muted">${shown}</span>` : ''}${r.used ? `<span class="tgused muted">${esc(tr('Last used {0}', relTime(r.used)))}</span>` : ''}</button>`;
}
function viewTags() {
  const rs = tg_collect();
  return `<div class="tgview"><p class="muted tgintro">${esc(tr('All your tags. A tap opens the tasks with that tag.'))}</p>${rs.length ? `<div class="tggrid">${rs.map(tg_card).join('')}</div>` : `<div class="empty">${esc(tr('No tags yet. Add a tag to a task and it shows up here.'))}</div>`}</div>`;
}
