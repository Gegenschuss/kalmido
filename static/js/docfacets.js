// @ts-check
/* Kalmido web client: the filters of the documents below the file store's tree (2.772.0, #4890; stage 3 of "Files +
   Documents", plan #4885). Classic script sharing the global scope with the others; loaded with the saved views
   (lazyload.js 'docviews') by the panel of Files (ablage.js ab_panelHtml), after "All documents" / "To review".
   - groups over ALL documents of the shown workspace: Sender, Document type, Tags, Archive number, then every custom field
     of type selection or checkbox; each row = name + number of documents (GET /api/docs/facets, the same rights and the
     same area as the list: only values and numbers of documents the person sees, no office receipts)
   - a click shows "All documents" with only this filter (docs.js dc_facetGo), the row is marked; a second click takes the
     filter away again
   - Archive number: a small field "Number or range" (143 or 140-150), below it "without" / "with archive number" (n)
   - each group folds on its own, kept per person (LS 'abFacOpen'), folded the first time; only values with documents; over
     DFC_TOP values the most used first and "Show all"
   - the head of a group has its button to manage it (Senders, types and fields / the documents' settings)
   Phones have no panel: the same groups stand in the filter sheet of the documents list (docs.js dc_fltHtml). */
'use strict';

const DFC = {data: null, key: '', at: 0, loading: null, all: new Set()};
const DFC_TOP = 15;
const DFC_TTL = 60000;
// the query of the numbers: the workspace shown and, like the list (docs.js dc_params), no office receipts in "All" / "Private"
function dfc_query() {
  const ws = typeof wsCur === 'function' ? wsCur() : 'all', p = new URLSearchParams({ws});
  if (ws === 'all' || ws === 'private') p.set('area', 'private');
  return p.toString();
}
async function dfc_load(force) {
  const key = dfc_query();
  if (!force && DFC.data && DFC.key === key && Date.now() - DFC.at < DFC_TTL) return;
  if (DFC.loading && DFC.key === key) return DFC.loading;
  DFC.key = key;
  DFC.loading = (async () => {
    try { const j = await rawFetch('GET', '/api/docs/facets?' + key); if (DFC.key === key) { DFC.data = j; DFC.at = Date.now(); } }
    catch { /* the groups stay as they were */ }
    finally { DFC.loading = null; }
    if (typeof sbb_sync === 'function') sbb_sync('ablage');
  })();
  return DFC.loading;
}
// the documents list loaded its filters of the same workspace and area (docs.js dc_load): they are the numbers here too
function dfc_take(p, facets) {
  const q = new URLSearchParams(p), mine = new URLSearchParams(dfc_query());
  if (q.get('ws') !== mine.get('ws') || (q.get('area') || '') !== (mine.get('area') || '') || q.has('folder') || q.has('under') || !facets?.fields) return;
  const same = DFC.key === mine.toString() && JSON.stringify(DFC.data) === JSON.stringify(facets);
  Object.assign(DFC, {data: facets, key: mine.toString(), at: Date.now()});
  if (!same && typeof sbb_sync === 'function') sbb_sync('ablage');
}
const dfc_stale = () => { DFC.at = 0; };

// ---- state: folded, the active filter
const dfc_open = g => (LS.get('abFacOpen', []) || []).includes(g);
function dfc_toggle(g) { const x = new Set(LS.get('abFacOpen', []) || []); x.has(g) ? x.delete(g) : x.add(g); LS.set('abFacOpen', [...x]); if (typeof sbb_sync === 'function') sbb_sync('ablage'); }
// the list shows "All documents" with its own filters (not a saved view, not To review, not a folder's list)
const dfc_listOn = () => S.route.mod === 'docs' && !S.route.review && !S.route.dv && !S.route.id && typeof DC === 'object' && !DC.folder;
const dfc_arr = v => Array.isArray(v) ? v : v ? [v] : [];
// is the filter of a row active (the row is marked; its click takes it away again)
function dfc_isOn(g, v) {
  if (!dfc_listOn()) return false;
  const f = DC.f || {};
  if (g === 'sender' || g === 'type') return dfc_arr(f[g]).includes(v);
  if (g === 'tag') return (f.tg || {})[v] === 'in' || f.tag === v;
  if (g === 'asnhas') return f.asnHas === v;
  if (g === 'cf') return dfc_arr(f.cf).includes(v);
  return false;
}
// the part of the filters (docs.js dc_f0) a row sets
const dfc_part = (g, v) => g === 'tag' ? {tg: {[v]: 'in'}} : g === 'asnhas' ? {asnHas: v} : g === 'asn' ? {asn: v} : g === 'cf' ? {cf: [v]} : {[g]: [v]};
function dfc_pick(g, v) {
  if (dfc_isOn(g, v)) {  // the second click: only this filter goes, the others stay
    const f = DC.f;
    if (g === 'sender' || g === 'type') f[g] = dfc_arr(f[g]).filter(x => x !== v);
    else if (g === 'tag') { f.tg = {...(f.tg || {})}; delete f.tg[v]; if (f.tag === v) f.tag = ''; }
    else if (g === 'asnhas') f.asnHas = '';
    else if (g === 'cf') f.cf = dfc_arr(f.cf).filter(x => x !== v);
    DC.at = 0; dc_load();
    if (typeof sbb_sync === 'function') sbb_sync('ablage');
    return;
  }
  dc_facetGo(dfc_part(g, v));
}

// ---- drawing
const dfc_cnt = n => `<span class="c">${n}</span>`;
function dfc_row(g, v, icon, name, n) {
  const on = dfc_isOn(g, v);
  return `<button type="button" class="srow smod sbbi dfcr ${on ? 'on' : ''}" data-dfc="${g}" data-dfcv="${esc(v)}" aria-pressed="${on}">${ic(icon)}<span class="n">${esc(name)}</span>${dfc_cnt(n)}</button>`;
}
function dfc_group(g, label, body, manage, n) {
  const open = dfc_open(g);
  return `<div class="dfcg" data-dfcgrp="${esc(g)}"><div class="shead sgh dfch ${open ? '' : 'closed'}"><button type="button" class="sgt" data-dfcfold="${esc(g)}" aria-expanded="${open}">${ic('chev', 's fcar')}<span>${esc(label)}</span>${!open && n ? dfc_cnt(n) : ''}</button><span class="spacer"></span>`
    + `<button type="button" class="iconbtn dfcm" data-dfcm="${manage}" aria-label="${esc(manage === 'settings' ? tr('Settings of the documents') : tr('Senders, types and fields'))}" title="${esc(manage === 'settings' ? tr('Settings of the documents') : tr('Senders, types and fields'))}">${ic(manage === 'settings' ? 'gear' : 'list', 's')}</button></div>`
    + (open ? `<div class="dfcb" role="group" aria-label="${esc(label)}">${body()}</div>` : '') + '</div>';
}
// the values of a group: the most used first; over DFC_TOP only those and "Show all"
function dfc_list(key, items, row) {
  const sorted = [...items].sort((a, b) => b.count - a.count || String(a.name).localeCompare(String(b.name)));
  const all = DFC.all.has(key) || sorted.length <= DFC_TOP;
  return (all ? sorted : sorted.slice(0, DFC_TOP)).map(row).join('')
    + (sorted.length > DFC_TOP ? `<button type="button" class="linkbtn dfcall" data-dfcall="${esc(key)}">${all ? esc(tr('Show less')) : esc(tr('Show all ({0})', sorted.length))}</button>` : '');
}
function dfc_asnBody(a) {
  const f = dfc_listOn() ? DC.f || {} : {}, cur = f.asn || '';
  return `<form class="dfcasn" data-dfcasn="1"><input type="text" inputmode="numeric" name="asn" value="${esc(cur)}" placeholder="${esc(tr('Number or range'))}" aria-label="${esc(tr('Archive number: number or range, e.g. 140-150'))}" autocomplete="off">`
    + `<button type="submit" class="iconbtn" aria-label="${esc(tr('Filter'))}" title="${esc(tr('Filter'))}">${ic('search', 's')}</button></form>`
    + (a.without ? dfc_row('asnhas', 'without', 'hash', tr('without archive number'), a.without) : '')
    + (a.with ? dfc_row('asnhas', 'with', 'hash', tr('with archive number'), a.with) : '');
}
function dfc_sideHtml() {
  if (!(typeof ab_docsOn === 'function' && ab_docsOn())) return '';
  if (!DFC.data || DFC.key !== dfc_query() || Date.now() - DFC.at > DFC_TTL) setTimeout(() => dfc_load(), 0);
  const d = DFC.data; if (!d) return '';
  const lab = (k, list, icon) => list?.length ? dfc_group(k, tr({sender: 'Sender', type: 'Document type', tag: 'Tags'}[k]), () => dfc_list(k, list, x => dfc_row(k, x.ids.join(','), icon, x.name, x.count)), 'lists', list.length) : '';
  const a = d.asn || {with: 0, without: 0};
  const asn = a.with + a.without ? dfc_group('asn', tr('Archive number'), () => dfc_asnBody(a), 'settings', '') : '';
  const fields = (d.fields || []).map(x => dfc_group('cf:' + x.name.toLowerCase(), x.name, () => dfc_list('cf:' + x.name.toLowerCase(), x.values, v => dfc_row('cf', x.ids.join(',') + ':' + v.value, x.type === 'checkbox' ? 'check' : 'list', v.name, v.count)), 'lists', x.values.length)).join('');
  return `<div class="dfc" role="group" aria-label="${esc(tr('Filter'))}">${lab('sender', d.senders, 'user')}${lab('type', d.types, 'file')}${lab('tag', d.tags, 'tag')}${asn}${fields}</div>`;
}

// ---- events (the panel is redrawn by sbb_sync; one listener for all its rows)
document.addEventListener('click', e => {
  const t = /** @type {HTMLElement} */ (e.target);
  const fold = t.closest?.('[data-dfcfold]');
  if (fold) { dfc_toggle(fold.getAttribute('data-dfcfold') || ''); return; }
  const all = t.closest?.('[data-dfcall]');
  if (all) { const k = all.getAttribute('data-dfcall') || ''; DFC.all.has(k) ? DFC.all.delete(k) : DFC.all.add(k); if (typeof sbb_sync === 'function') sbb_sync('ablage'); return; }
  const m = t.closest?.('[data-dfcm]');
  if (m) { if (m.getAttribute('data-dfcm') === 'settings') settingsModal('docs'); else dc_settings(); return; }
  const r = t.closest?.('[data-dfc]');
  if (r) dfc_pick(r.getAttribute('data-dfc') || '', r.getAttribute('data-dfcv') || '');
});
document.addEventListener('submit', e => {
  const fm = /** @type {HTMLElement} */ (e.target).closest?.('[data-dfcasn]'); if (!fm) return;
  e.preventDefault();
  const inp = /** @type {HTMLInputElement|null} */ (fm.querySelector('input[name="asn"]'));
  const v = String(inp?.value || '').trim(), m = /^\s*(\d{1,9})\s*(?:[-–]\s*(\d{1,9})\s*)?$/.exec(v);
  if (!v) { if (dfc_listOn() && DC.f?.asn) { DC.f.asn = ''; DC.at = 0; dc_load(); } return; }
  if (!m) { toast(tr('Enter a number or a range such as 140-150')); return; }
  dc_facetGo({asn: m[2] ? `${m[1]}-${m[2]}` : m[1]});
});
