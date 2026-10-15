/* Kalmido web client: the areas (#1187). Modules that belong together are ONE entry in the sidebar, the tab bar and
   Settings > Modules, and one page with tabs for their parts: Office (office & finance, contacts, clients), Time (time
   tracking, focus timer), Review (review & journal, statistics), Home (home & life, family). Each part keeps its own
   route (#pomo, #stats, #contacts, #client/3 …), so every old link opens the area on that tab; the switches stay the old
   module keys (settings "features"), an area is on while one of its parts is.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.44.0 (#1187): [area, icon, name, parts: [route, icon, name, on(), feature keys]]; the area's id is its first part
const MG_AREAS = [
  ['office', 'receipt', N_('Office|area'), [['office', 'receipt', N_('Office & finance'), () => officeOn(), () => ['office']],
    ['contacts', 'users', N_('Contacts'), () => feat('contacts'), () => ['contacts']], ['clients', 'brief', N_('Clients'), () => clientsOn(), () => ['clients']]]],
  ['time', 'clock', N_('Time|area'), [['time', 'clock', N_('Time tracking'), () => timeOn(), () => ['time']], ['pomo', 'timer', N_('Focus timer'), () => feat('pomo'), () => ['pomo']]]],
  ['review', 'journal', N_('Review|area'), [['review', 'journal', N_('Review & journal'), () => feat('review'), () => ['review']], ['stats', 'chart', N_('Statistics'), () => feat('stats'), () => ['stats']]]],
  ['life', 'home', N_('Home|area'), [['life', 'home', N_('Home & life'), () => lifeOn(), () => LIFE_MODS], ['family', 'family', N_('Family'), () => famOn(), () => ['family']]]]];
const MG_IDS = MG_AREAS.map(a => a[0]);
const mg_area = id => MG_AREAS.find(a => a[0] === id) || null;
const mg_areaOf = mod => MG_AREAS.find(a => a[3].some(p => p[0] === mod)) || null;
const mg_parts = a => a ? a[3].filter(p => p[3]()) : [];
const mg_on = id => mg_parts(mg_area(id)).length > 0;
const mg_feats = id => (mg_area(id)?.[3] || []).flatMap(p => p[4]());
// the tab the area opens with: the one last used on this device (LS mgTab), else its first switched-on part
function mg_target(id) {
  const ps = mg_parts(mg_area(id)), last = (LS.get('mgTab', {}) || {})[id];
  return (ps.find(p => p[0] === last) || ps[0] || [id])[0];
}
function mg_seen(mod) {
  const a = mg_areaOf(mod); if (!a) return;
  const o = LS.get('mgTab', {}) || {}; if (o[a[0]] !== mod) { o[a[0]] = mod; LS.set('mgTab', o); }
}
// an old link to a part that is off now opens the area on another tab (null: nothing of the area is on)
function mg_alt(mod) { const a = mg_areaOf(mod); return a && !a[3].find(p => p[0] === mod)[3]() && mg_parts(a).length ? mg_target(a[0]) : null; }
// the header: the area's name above its tabs; with one part on (no tabs) that part's own name stays
const mg_title = mod => { const a = mg_areaOf(mod); return a && mg_parts(a).length > 1 ? tr(a[2]) : ''; };
// the tabs on top of an area's page (only with two parts or more on); the route of a part = data-go
function mg_tabsHtml(mod) {
  const a = mg_areaOf(mod); if (!a || S.me?.kid) return '';
  mg_seen(mod);
  const ps = mg_parts(a); if (ps.length < 2) return '';
  return `<div class="seg mgtabs" role="tablist" aria-label="${esc(tr(a[2]))}" data-mgtabs="${a[0]}">${ps.map(([m, i, n]) => `<button type="button" role="tab" data-go="${m}" aria-selected="${m === mod}" class="${m === mod ? 'on' : ''}">${ic(i, 's')}<span>${esc(tr(n))}</span>${m === 'time' && S.timer || m === 'pomo' && S.pomo ? '<span class="recdot"></span>' : ''}</button>`).join('')}</div>`;
}
const mg_wrap = (mod, html) => mg_tabsHtml(mod) + html;
// ---- the sidebar row of an area. Hidden (Settings > Appearance > Sidebar) while every part is ("e:<route>" of each part,
// so an arrangement from before 2.44.0 that hid both still hides the area, and 2.43.1 reads what this one writes)
const mg_sideKeys = id => mg_area(id)[3].map(p => p[0]);
const mg_sideHidden = (id, hid) => mg_sideKeys(id).every(k => hid('e:' + k));
function mg_sideRow(id, hid) {
  const a = mg_area(id), here = mg_areaOf(S.route.mod) === a;
  if (!mg_on(id) || (mg_sideHidden(id, hid) && !here)) return '';
  const rec = id === 'time' && (S.timer || S.pomo), req = id === 'life' && famOn() ? (S.kids || []).reduce((n, k) => n + (k.requests || 0), 0) : 0;
  const after = rec ? '<span class="c"><span class="recdot"></span></span>' : req ? `<span class="c nunread">${req}</span>` : '';
  return `<button class="srow smod ${here ? 'on' : ''}" data-go="${mg_target(id)}" data-mgside="${id}">${ic(a[1])}<span class="n">${esc(tr(a[2]))}</span>${after}</button>`;
}
// [keys, name] for the sidebar editor (one check box per area, for all its parts)
const mg_sideEntry = id => mg_on(id) ? [mg_sideKeys(id).join(','), mg_area(id)[2]] : null;
// ---- the tab bar (phone): one tab per area ("a:<id>"); a tab pinned before 2.44.0 for a part becomes its area's tab
const MG_TAB_OLD = {'m:pomo': 'a:time', time: 'a:time', stats: 'a:review', 'm:family': 'a:life', office: 'a:office'};
const mg_tabIds = ids => ids ? [...new Set(ids.map(x => MG_TAB_OLD[x] || x))] : ids;
function mg_tabItem(id) {
  const a = mg_area(id.slice(2)); if (!a || !mg_on(a[0])) return null;
  return {id, go: mg_target(a[0]), icon: ic(a[1], 'l'), ico: a[1], label: tr(a[2]), mod: a[0], area: a[0]};
}
const mg_tabOpts = opt => MG_IDS.filter(mg_on).map(id => opt('a:' + id, tr(mg_area(id)[2]))).join('');
// ---- Settings > Modules: ONE switch per area; its parts below it (each can still be switched on its own)
const mg_featOn = k => k.startsWith('a:') ? mg_on(k.slice(2)) : feat(k);
const MG_DESC = {office: N_('Office & finance (quotations, services, documents; needs an organisation), your contacts and the clients'),
  time: N_('Time tracking on tasks with reports, and the focus timer; finished focus sessions can count as time entries'),
  review: N_('Your day and week in review with a private journal, and the statistics'),
  life: N_('Home & life (contracts, devices, staying in touch, health, trips, read later) and family')};
function mg_modAreaHtml(id, partRow) {
  const a = mg_area(id), on = mg_on(id), ks = a[3].flatMap(p => p[4]());
  return `<div class="modrow mgarea ${on ? '' : 'off'}" data-mgrow="${id}"><label class="mmain"><span class="swc"><input type="checkbox" data-mgarea="${id}" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${tr(a[2])}</b><small class="muted">${tr(MG_DESC[id])}</small></span></label>
    <details class="mopt mgparts"><summary>${tr('Parts: {0}', a[3].map(p => tr(p[2])).join(', '))}</summary><div class="modlist">${ks.map(partRow).join('')}</div></details></div>`;
}
function mg_setSync(md) {
  for (const el of $$('[data-mgarea]', md)) if (el.matches('input')) el.checked = mg_on(el.dataset.mgarea);
  $$('[data-mgrow]', md).forEach(r => r.classList.toggle('off', !mg_on(r.dataset.mgrow)));
}
// the area's switch: all its parts on or off, ONE undo step
async function mg_areaSwitch(md, el) {
  const id = el.dataset.mgarea, on = el.checked, n = tr(mg_area(id)[2]);
  const fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
  for (const k of mg_feats(id)) on ? fs.add(k) : fs.delete(k);
  await setApply({features: FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',')}, on ? tr('{0} on', n) : tr('{0} off', n));
  for (const x of $$('[data-feat]', md)) { x.checked = feat(x.dataset.feat); x.closest('[data-modrow]')?.classList.toggle('off', !x.checked); }
  mg_setSync(md); modCountsSync(md);
  if (id === 'time' && on && !$('#s-trnd', md)) { const cur = LS.get('settingsSec'); md._noflush = true; md.remove(); settingsModal(cur); }  // the time options
}
