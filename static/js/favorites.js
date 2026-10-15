/* Kalmido web client: favourite lists and projects (2.40.0, #1361).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   The stars are personal (user setting fav_lists, set with PUT /api/lists/<id>/favorite); nobody else sees them.
   - the list menu (header "…", sidebar right-click / long press) and a star in the list header set / clear one
   - the sidebar: a section "Favourites" on top; "Only favourites" (fav_only) folds every other list under "More lists (N)"
   - Today, Tomorrow, Next 7 days, Now doable and My tasks: "Only favourites" per view (view menu, fav_views) */
'use strict';

const FAV_VIEWS = ['today', 'tomorrow', 'week', 'doable', 'assigned'];
const VW_FAV_HELP = N_('Star the lists and projects you really work on: the star next to the list title, or the list menu (…), a right-click or a long press in the sidebar > Add to favourites. Other members do not see your stars; only your own agents see which of their lists are your favourites. Your favourites stand on top of the sidebar; the filter button there (Only favourites) folds every other list under “More lists”. Today, Tomorrow, Next 7 days, Now doable and My tasks can show only the tasks of your favourites: … > Only favourites.');  // Settings > Help
const favIds = () => (S.settings?.fav_lists || '').split(',').filter(Boolean).map(Number);
const favIs = id => favIds().includes(+id);
const favAny = () => favIds().some(id => { const l = listById(id); return l && !l.archived && !l.is_inbox; });
const favOnly = () => S.settings?.fav_only === '1' && favAny();
const favViewOn = (k = S.route.key) => FAV_VIEWS.includes(k) && (S.settings?.fav_views || '').split(',').includes(k);
// a task of a view filtered to favourites: only from a starred list (or a list below a starred one is not a thing: lists only)
const favKeep = (t, k = S.route.key) => !favViewOn(k) || favIs(t.list_id);

async function favSet(id, on) {
  const ids = favIds().filter(x => x !== +id);
  if (on) ids.push(+id);
  S.settings.fav_lists = ids.join(',');
  render();
  toast(on ? tr('Added to favourites') : tr('Removed from favourites'));
  try { const r = await api(on ? 'PUT' : 'DELETE', `/api/lists/${+id}/favorite`, on ? {on: true} : undefined); if (r && typeof r.fav_lists === 'string') S.settings.fav_lists = r.fav_lists; }
  catch { try { await load(); } catch { /* offline */ } render(); }
}
async function favSetting(key, val) {
  S.settings[key] = val;
  render();
  try { await api('PATCH', '/api/settings', {[key]: val}); } catch { try { await load(); } catch { /* offline */ } render(); }
}
// the list menu entry (dialogs.js listMenuItems): the header's "…" and the sidebar's context menu (long press on a phone)
const favMenuItem = l => l && !l.is_inbox && !l.archived ? (favIs(l.id) ? {label: tr('Remove from favourites'), icon: 'star', fn: () => favSet(l.id, false)}
  : {label: tr('Add to favourites'), icon: 'star', fn: () => favSet(l.id, true)}) : null;
// the star in the list header (render.js, after the title)
function favTopBtn(l) {
  if (!l || l.is_inbox || l.archived) return '';
  const on = favIs(l.id), lab = on ? tr('Remove from favourites') : tr('Add to favourites');
  return `<button type="button" class="iconbtn hfav tf ${on ? 'on' : ''}" data-fav="${l.id}" aria-pressed="${on}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('star', 's')}</button>`;
}
// the sidebar's section on top (render.js renderSide; lists = the shown lists, listRow = its row)
function favSideHtml(lists, listRow, head) {
  const fl = lists.filter(l => favIs(l.id)); if (!fl.length) return '';
  fl.sort((a, b) => favIds().indexOf(a.id) - favIds().indexOf(b.id));
  const only = favOnly(), lab = tr('Only favourites');
  const acts = `<button type="button" data-fav-only class="${only ? 'on' : ''}" aria-pressed="${only}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('filter', 's')}</button>`;
  return `<div class="sgroup sg-favs">${head('favs', tr('Favourites'), acts, fl.length)}${sideOpen('favs') ? fl.map(listRow).join('') : ''}</div>`;
}
// the lists of the group "Lists": with "Only favourites" every other list folds under "More lists (N)" (open for the session)
function favListsHtml(lh, lists) {
  if (!favOnly() || S.listReorder) return lh;
  const n = lists.filter(l => !favIs(l.id)).length, open = !!S.favMore;
  if (!n) return lh;
  return `<button type="button" class="srow sfavmore ${open ? '' : 'closed'}" data-fav-more aria-expanded="${open}">${ic('chev', 's fcar')}<span class="n">${esc(tr('More lists ({0})', n))}</span></button>${open ? `<div class="sfavrest">${lh}</div>` : ''}`;
}
// the view menu (render.js topMoreItems): "Only favourites" in the views across lists
function favViewItems() {
  const k = S.route.key;
  if (S.route.mod !== 'tasks' || !FAV_VIEWS.includes(k) || !favAny()) return [];
  const on = favViewOn(k);
  return [{label: tr('Only favourites'), icon: 'star', on, fn: () => {
    const ks = (S.settings.fav_views || '').split(',').filter(x => x && x !== k);
    if (!on) ks.push(k);
    favSetting('fav_views', ks.join(','));
  }}];
}
// a hint above a filtered view, with a way back
const favViewNote = () => favViewOn() && favAny() ? `<div class="favnote muted">${ic('star', 's')}<span>${esc(tr('Only tasks from your favourites'))}</span><button type="button" class="linkbtn" data-fav-view-off>${esc(tr('Show all'))}</button></div>` : '';

// 2.46.1 (#1361): Settings > Appearance > Favourites: quieter pushes from lists without a star (default off) and the one-time
// suggestion of a busy list (default on)
const lc_favSetHtml = (chk, hint) => `<h4 id="s-fav-h">${tr('Favourites')}</h4>
      <div class="row">${chk('s-favq', S.settings?.fav_quiet === '1', tr('Quieter pushes from lists without a star'))}</div>
      ${hint(tr('While you have favourites, lists without a star send pushes only for @mentions, replies to you, assignments, reminders and approvals. The News stay complete; a list bell set to All wins.'))}
      <div class="row">${chk('s-favs', S.settings?.fav_suggest !== '0', tr('Suggest favourites'))}</div>
      ${hint(tr('After two weeks of much work in a list without a star, Kalmido asks once whether to add it to your favourites. It never sets a star by itself.'))}`;
// once per start of the app: a busy list without a star is offered (the server asks about each list only once)
async function lc_favSuggest() {
  if (S.settings?.fav_suggest === '0' || !navigator.onLine) return;
  try {
    const r = await api('POST', '/api/favorites/suggestion', {});
    const l = r && r.list_id && listById(r.list_id);
    if (l && !favIs(l.id)) toast(tr('You worked a lot in “{0}” these two weeks. Add it to your favourites?', lname(l)), () => favSet(l.id, true), 12000, tr('Add to favourites'));
  } catch { /* offline or an older server: no suggestion */ }
}

document.addEventListener('click', e => {
  const t = e.target.closest?.('[data-fav],[data-fav-only],[data-fav-more],[data-fav-view-off]'); if (!t) return;
  e.preventDefault(); e.stopPropagation();
  if (t.hasAttribute('data-fav')) favSet(+t.dataset.fav, !favIs(+t.dataset.fav));
  else if (t.hasAttribute('data-fav-only')) favSetting('fav_only', favOnly() ? '0' : '1');
  else if (t.hasAttribute('data-fav-more')) { S.favMore = !S.favMore; renderSide(); }
  else favSetting('fav_views', (S.settings.fav_views || '').split(',').filter(x => x && x !== S.route.key).join(','));
}, true);
