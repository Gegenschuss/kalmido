// @ts-check
/* Kalmido web client: saved views of the documents search (2.579.0, #4802; server: kalmido/docs/dviews.py, a kind of the
   shared core). Classic script sharing the global scope with the others; loaded on demand (lazyload.js 'docviews') by the
   documents list, the sidebar of Files and Today.
   - "Save view" in the documents' bar keeps the search field, the filters and the sort under a name (#ablage/v/<id> opens it; the old #docs/v/<id> leads there)
   - the sidebar lists the views of the shown workspace under "Documents" / "To review", each with its number of hits
   - the view's menu (its "…" at the top of the list, right-click / long press on its row): rename, take over the current
     filters, favourite, show on Today, share with everyone of the organisation (admins in an organisation's workspace),
     delete (with Undo)
   - Today: a block per view switched on (user setting dv_today) with the first five hits and the number
   Hits and numbers come from the server with the rights of the person looking. */
'use strict';

const DCV = {items: null, ws: null, at: 0, loading: null, hits: {}, applied: null};
const DCV_TODAY_N = 5;
const dcv_url = id => `/api/obj/docview/${+id}`;
const dcv_get = id => (DCV.items || []).find(v => v.id === +id) || null;
const dcv_todayIds = () => (S.settings?.dv_today || '').split(',').filter(Boolean).map(Number);
const dcv_isToday = id => dcv_todayIds().includes(+id);
// only an admin of the organisation the view searches shares it with everyone of it (the server decides again)
const dcv_mayShare = v => !!v && /^org:\d+$/.test(v.ws || '') && (S.me?.workspaces || []).find(w => w.id === +v.ws.slice(4))?.role === 'admin';

// ---- loading
async function dcv_load(force) {
  const ws = typeof wsCur === 'function' ? wsCur() : 'all';
  if (!force && DCV.items && DCV.ws === ws && Date.now() - DCV.at < 30000) return DCV.items;
  if (DCV.loading && DCV.ws === ws) return DCV.loading;
  DCV.ws = ws;
  DCV.loading = (async () => {
    try { const j = await rawFetch('GET', '/api/docs/views?ws=' + encodeURIComponent(ws)); if (DCV.ws === ws) { DCV.items = j.items || []; DCV.at = Date.now(); } }
    catch { DCV.items = DCV.items || []; }
    finally { DCV.loading = null; }
    if (typeof sbb_sync === 'function') sbb_sync('ablage');
    if (S.route.mod === 'docs' && typeof dc_draw === 'function') dc_draw();
    if (S.route.mod === 'tasks' && S.route.key === 'today' && dcv_todayIds().length) renderView();
    return DCV.items;
  })();
  return DCV.loading;
}
const dcv_stale = () => { DCV.at = 0; DCV.hits = {}; };

// ---- the sidebar (ablage.js: the group "Saved filters" under Files)
function dcv_sideHtml() {
  const ws = typeof wsCur === 'function' ? wsCur() : 'all';
  if (!DCV.items || DCV.ws !== ws || Date.now() - DCV.at > 60000) setTimeout(() => dcv_load(), 0);
  const r = S.route;
  return (DCV.items || []).map(v => sbb_row('ablage/v/' + v.id, 'filter', v.title, r.mod === 'docs' && r.dv === v.id, `data-sbbpart="docs-view" data-dcvid="${v.id}"`,
    `${v.shared_all ? `<span class="dcv-all" title="${esc(tr('Shared with everyone of the organisation'))}">${ic('users', 's')}</span>` : ''}${v.count != null ? `<span class="c">${v.count}</span>` : ''}`)).join('');
}

// ---- the documents list: apply a view, keep the current search
function dcv_queryNow() {
  const p = dc_params();
  for (const k of ['ws', 'limit', 'offset', 'facets']) p.delete(k);
  return p.toString();
}
function dcv_apply(v) {
  const p = new URLSearchParams(v?.query || ''), f = dc_f0();
  for (const k of ['sender', 'type', 'folder']) f[k] = p.getAll(k);
  for (const ids of p.getAll('tag')) f.tg[ids] = 'in';
  for (const ids of p.getAll('not_tag')) f.tg[ids] = 'not';
  if (p.get('tag_mode') === 'all') f.tmode = 'all';
  f.from = p.get('from') || ''; f.to = p.get('to') || ''; f.afrom = p.get('added_from') || ''; f.ato = p.get('added_to') || '';
  f.notag = p.get('no_tag') === '1'; f.nosender = p.get('no_sender') === '1'; f.review = p.get('review') === '1';
  f.ftype = (p.get('ftype') || '').split(',').filter(Boolean);
  f.asn = p.get('asn') || ''; f.asnHas = p.get('has_asn') === '1' ? 'with' : p.get('no_asn') === '1' ? 'without' : ''; f.cf = p.getAll('cf');  // 2.772.0 (#4890)
  DC.f = f; DC.q = p.get('q') || ''; DC.under = p.get('under') || null;
  const qi = $('#dc-q'); if (qi) qi.value = DC.q;  // the field keeps its text in a redraw (docs.js "Remove filter q"): its next input would bring the old search back
  if (typeof dc_qTimer !== 'undefined') clearTimeout(dc_qTimer);
  DC.vsort = v && p.get('sort') ? {k: p.get('sort'), d: p.get('dir') === 'asc' ? 'asc' : 'desc'} : v ? {k: 'date', d: 'desc'} : null;
  DC.more = false; DC.at = 0; DC.facets = null;
  DCV.applied = v ? {id: v.id, query: v.query} : null;
}
// the route changed (docs.js viewDocs): #ablage/v/<id> applies the view, leaving it empties the search again
function dcv_routeSync() {
  const id = S.route.mod === 'docs' ? S.route.dv || null : null;
  if ((DC.dv || null) === id) return;
  const was = DC.dv; DC.dv = id;
  if (!id) { if (was) { dcv_apply(null); dc_load(); } return; }
  const v = dcv_get(id);
  if (v) { dcv_apply(v); dc_load(); return; }
  DC.dv = null;  // not loaded yet: again once the views are there
  dcv_load(true).then(() => { if (S.route.mod === 'docs' && S.route.dv === id) { if (dcv_get(id)) { dcv_routeSync(); dc_draw(); } else { toast(tr('This view does not exist or you cannot see it.')); go('ablage/docs'); } } });
}
const dcv_changed = () => !!DC.dv && !!DCV.applied && DCV.applied.id === DC.dv && dcv_queryNow() !== new URLSearchParams(DCV.applied.query || '').toString();
// the documents' bar: "Save view"; in a view: its name, a mark when the search differs from what it keeps, its menu
function dcv_barHtml() {
  const v = DC.dv ? dcv_get(DC.dv) : null;
  if (!v) return `<button type="button" class="btn sm dcv-save" data-dcv="save">${ic('filter', 's')} <span>${esc(tr('Save view'))}</span></button>`;
  const ch = dcv_changed();
  return `<span class="dcv-cur"><button type="button" class="btn sm on dcv-name" data-dcv="menu" data-dcvid="${v.id}" aria-haspopup="menu">${ic('filter', 's')} <span>${esc(v.title)}</span>${ch ? `<span class="dcv-dirty" title="${esc(tr('Changed since it was saved'))}">*</span>` : ''}</button>${ch && v.role !== 'view' ? `<button type="button" class="btn sm pri" data-dcv="update" data-dcvid="${v.id}">${esc(tr('Update view'))}</button>` : ''}</span>`;
}

// ---- writes (the core's routes: version check, history, trash with undo)
async function dcv_save() {
  const name = await askDialog({title: tr('Save view'), body: tr('Keeps the search, the filters and the sort under a name. It shows in the sidebar under Documents.'),
    input: {value: '', placeholder: tr('Name of the view'), max: 120}, ok: tr('Save'), cancel: undefined, after: undefined});
  if (!name || !name.trim()) return;
  const ws = typeof wsCur === 'function' ? wsCur() : 'all';
  let v; try { v = await api('POST', '/api/obj/docview', {title: name.trim(), query: dcv_queryNow(), ws}); } catch { return; }
  dcv_stale(); await dcv_load(true);
  toast(tr('View “{0}” saved', v.title));
  go('ablage/v/' + v.id);
}
async function dcv_patch(v, b, label) {
  const old = dcv_get(v.id) || v, back = Object.fromEntries(Object.keys(b).map(k => [k, old[k]]));
  let r; try { r = await api('PATCH', dcv_url(v.id), {...b, expect_updated_at: old.updated_at}); } catch (x) { if (x?.status === 409) { dcv_stale(); dcv_load(true); } return null; }
  if ('query' in b && DC.dv === v.id) DCV.applied = {id: v.id, query: r.query};
  dcv_stale(); await dcv_load(true);
  const again = async (vals) => { const cur = dcv_get(v.id); if (!cur) return; try { await api('PATCH', dcv_url(v.id), {...vals, expect_updated_at: cur.updated_at}); } catch { /* shown */ } if ('query' in vals && DC.dv === v.id) { const n = dcv_get(v.id); dcv_stale(); await dcv_load(true); const m = dcv_get(v.id) || n; if (m) { dcv_apply(m); dc_load(); } } else { dcv_stale(); dcv_load(true); } };
  offerUndo(label, histAdd({label, undo: () => again(back), redo: () => again(b)}));
  return r;
}
async function dcv_rename(v) {
  const name = await askDialog({title: tr('Rename view'), input: {value: v.title, placeholder: tr('Name of the view'), max: 120}, ok: tr('Rename'), cancel: undefined, after: undefined});
  if (!name || !name.trim() || name.trim() === v.title) return;
  dcv_patch(v, {title: name.trim()}, tr('View renamed'));
}
const dcv_update = v => dcv_patch(v, {query: dcv_queryNow()}, tr('View “{0}” now keeps the current filters', v.title));
async function dcv_delete(v) {
  try { await api('POST', dcv_url(v.id) + '/trash'); } catch { return; }
  if (dcv_isToday(v.id)) dcv_todaySet(v.id, false, true);
  dcv_stale(); await dcv_load(true);
  if (DC.dv === v.id) go('ablage/docs');
  const back = async () => { try { await api('POST', dcv_url(v.id) + '/restore'); } catch { /* shown */ } dcv_stale(); dcv_load(true); };
  offerUndo(tr('View “{0}” deleted', v.title), histAdd({label: tr('Delete view'), undo: back, redo: async () => { try { await api('POST', dcv_url(v.id) + '/trash'); } catch { /* shown */ } dcv_stale(); dcv_load(true); }}));
}
async function dcv_shareAll(v, on) {
  try { await api('POST', `/api/docs/views/${v.id}/share`, {all: on}); } catch { return; }
  dcv_stale(); await dcv_load(true);
  toast(on ? tr('Everyone of the organisation sees this view now (with their own rights)') : tr('Only you see this view now'));
}
function dcv_todaySet(id, on, quiet) {
  const ids = dcv_todayIds().filter(x => x !== +id);
  if (on) ids.push(+id);
  favSetting('dv_today', ids.join(','));
  if (!quiet) toast(on ? tr('Shown on Today') : tr('No longer shown on Today'));
}
function dcv_menuItems(v) {
  if (!v) return [];
  const key = 'r:docview:' + v.id, fav = typeof fv2_is === 'function' && fv2_is(key), w = v.role !== 'view';
  return [
    w ? {label: tr('Rename…'), icon: 'edit', fn: () => dcv_rename(v)} : null,
    w ? {label: tr('Use the current filters'), icon: 'filter', fn: () => dcv_update(v)} : null,
    typeof fv2_set === 'function' ? {label: fav ? tr('Remove from favourites') : tr('Add to favourites'), icon: 'star', on: fav, fn: () => fv2_set(key, !fav)} : null,
    {label: tr('Show on Today'), icon: 'sun', on: dcv_isToday(v.id), fn: () => dcv_todaySet(v.id, !dcv_isToday(v.id))},
    v.role === 'manage' && dcv_mayShare(v) ? {label: tr('Share with everyone of the organisation'), icon: 'users', on: v.shared_all, fn: () => dcv_shareAll(v, !v.shared_all)} : null,
    v.role === 'manage' ? '-' : null,
    v.role === 'manage' ? {label: tr('Delete view'), icon: 'trash', cls: 'danger', fn: () => dcv_delete(v)} : null].filter(Boolean);
}

// ---- Today: one block per view switched on (dashboard.js LY.today, render.js)
const dcv_todayBlocks = () => dcv_todayIds().map(id => ['dv' + id, dcv_get(id)?.title || N_('Saved view'), 'filter', 'full']);
async function dcv_hitsLoad(id) {
  const h = DCV.hits[id];
  if (h && (h.busy || Date.now() - h.at < 60000)) return;
  DCV.hits[id] = {...(h || {}), busy: true, at: Date.now()};
  try { const j = await rawFetch('GET', `/api/docs/views/${id}/hits?limit=${DCV_TODAY_N}`); DCV.hits[id] = {at: Date.now(), total: j.total, docs: j.docs || [], view: j.view}; }
  catch (x) { DCV.hits[id] = {at: Date.now(), gone: x?.status === 404, docs: [], total: 0}; }
  if (S.route.mod === 'tasks' && S.route.key === 'today') renderView();
}
function dcv_todayCard(id) {
  const h = DCV.hits[id];
  if (!h || Date.now() - h.at > 60000) dcv_hitsLoad(id);
  if (h?.gone) return '';
  const v = h?.view || dcv_get(id), name = v?.title || tr('Saved view');
  const rows = (h?.docs || []).map(d => `<li><a href="#ablage/${d.id}">${ic('file', 's')}<span class="dwt"><b>${esc((typeof dc_title === 'function' ? dc_title(d) : d.title || d.name) || '')}</b>${d.date ? ` <span class="muted">${esc(dayLabel(d.date, true))}</span>` : ''}</span></a></li>`).join('');
  return `<section class="dcard dcv-today" aria-labelledby="dcvh-${id}"><h3 id="dcvh-${id}">${ic('filter', 's')}<span>${esc(name)}</span>${h && !h.busy ? `<span class="dcn">${h.total}</span>` : ''}<span class="spacer"></span><a class="linkbtn" href="#ablage/v/${id}">${esc(tr('Show all'))}</a></h3>
    ${h && !h.busy ? rows ? `<ul class="dwl">${rows}</ul>` : `<p class="muted">${esc(tr('No documents in this view.'))}</p>` : `<p class="muted">${esc(tr('Loading…'))}</p>`}</section>`;
}
function dcv_todayParts() {
  if (!DCV.items && !DCV.loading) dcv_load();
  return Object.fromEntries(dcv_todayIds().map(id => ['dv' + id, dcv_todayCard(id)]));
}

document.addEventListener('click', e => {
  const t = /** @type {any} */ (e.target).closest?.('[data-dcv]'); if (!t) return;
  e.preventDefault();
  const a = t.dataset.dcv, v = dcv_get(t.dataset.dcvid);
  if (a === 'save') dcv_save();
  else if (a === 'menu') menu(t, dcv_menuItems(v));
  else if (a === 'update' && v) dcv_update(v);
});
// right-click / long press on a view's row in the sidebar: its menu (sidebar rows of other kinds keep theirs)
document.addEventListener('contextmenu', e => {
  const t = /** @type {any} */ (e.target).closest?.('#side [data-sbbpart="docs-view"]'); if (!t) return;
  const v = dcv_get(t.dataset.dcvid); if (!v) return;
  e.preventDefault(); e.stopPropagation();
  menu(t, dcv_menuItems(v));
}, true);
if (typeof sbb_sync === 'function') setTimeout(() => dcv_load(), 0);  // loaded later than the panel was drawn (lazyload.js): its rows now
