// @ts-check
/* Kalmido web client: "Recently edited" (2.769.0, #5352), loaded on demand (lazyload.js LD_MODS recent).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   ONE server route (GET /api/recent, kalmido/collab/recent.py) for three places:
   - 2.880.0 (#5561): the overview "All workspaces" of Knowledge, Files and Reading (areas.js spo_recentHtml, called by wiki.js,
     ablage.js and readlater.js) is a calm list of rows of one kind: "Recently edited" (the clock, opens the page below),
     Private, each organisation, Shared with me; the trash set off small at the end. No chips, no list of items on it.
   - the page "Recently edited" of each of the three (#wiki/recent, #ablage/recent, #reading/recent, zle_pageHtml): the arrow
     back to the overview (the address carries the page: the phone's Back returns there too), "Pinned" (the person's
     favourites of the area), chips to filter by workspace (All / Private / an organisation ...), then the last 20 pages, files
     and read-later entries, newest first, each only name and when (+ who, when it was not the person herself)
   - the start page's block "Recently edited" (dashboard.js dashCard 'recent'): 8 entries; under "All" from every workspace
     with the chip, in one workspace only its own; "More" leads to the overview.
   The rows keep their height while loading (a placeholder of the same height): nothing jumps when the answer comes. */
'use strict';

const ZLE = {d: {}, busy: {}, more: false, f: {}};  // 2.880.0 (#5561): f = the chosen filter of the page per area
const ZLE_N = 20, ZLE_HOME_N = 8;
// area -> [icon, name, the view's route]
const ZLE_AREA = {wiki: ['note', N_('Knowledge|area')], files: ['file', N_('File store')], reading: ['bookmark', N_('Read later')]};
const zle_key = (sp, n) => sp + '|' + n;
async function zle_load(sp, n) {
  const k = zle_key(sp, n); if (ZLE.busy[k]) return;
  ZLE.busy[k] = true;
  const v0 = S.v;
  try { const j = await api('GET', `/api/recent?space=${encodeURIComponent(sp)}&limit=${n}`); ZLE.d[k] = {items: j.items || [], v: v0, err: ''}; }
  catch (e) { if (e.message === 'auth') { ZLE.busy[k] = false; return; } ZLE.d[k] = {items: ZLE.d[k]?.items || null, v: v0, err: e instanceof Offline ? tr('Only available online.') : e.message || tr('unknown')}; }
  ZLE.busy[k] = false;
  if (['home', 'wiki', 'ablage', 'reading'].includes(S.route.mod)) viewSafeRender();
}
// the items of a workspace key ('all' | 'private' | 'org:<id>'), loaded again after a change (S.v)
function zle_data(sp, n) {
  const d = ZLE.d[zle_key(sp, n)];
  if (!d || d.v !== S.v) zle_load(sp, n);
  return d || null;
}
// where a tap leads: the page, the file (its document view or folder), the read-later list of its workspace
function zle_href(x) {
  if (x.area === 'wiki') return '#wiki/' + x.id;
  if (x.area === 'files') return '#ablage/' + x.id;
  return '#' + (typeof rd_all === 'function' && rd_all() && x.space !== 'shared' ? 'reading/s/' + x.space : 'reading');
}
// the chip of the item's workspace (its symbol and name), 'shared' = shared with me from outside
const zle_chip = sp => `<span class="zlec">${sp === 'shared' ? ic('users', 's') : wsIcon(sp)}<span>${esc(sp === 'shared' ? tr('Shared with me') : wsName(sp))}</span></span>`;
// 2.880.0 (#5561): who only when it was someone else; o.page = the page "Recently edited": name and when only (no chip, no place)
function zle_rowHtml(x, chip, o = {}) {
  const a = ZLE_AREA[x.area] || ZLE_AREA.files, who = x.by_name && x.by !== S.me?.id ? esc(x.by_name) + ' · ' : '';
  return `<li><a href="${esc(zle_href(x))}" class="zler" data-zle="${esc(x.area + ':' + x.id)}" title="${esc(tr(a[1]))}">${ic(a[0], 's')}<span class="zlet"><span class="zlen">${esc(x.title || tr(a[1]))}</span>${x.place && !o.page ? `<small class="muted zlep">${esc(x.place)}</small>` : ''}</span>${chip ? zle_chip(x.space) : ''}<small class="muted zlew">${who}<time datetime="${esc(x.at || '')}">${esc(x.at ? relTime(x.at) : '')}</time></small></a></li>`;
}
// the rows, or while loading a placeholder of the same height (n rows), or the empty text
function zle_listHtml(d, n, chip, empty, o = {}) {
  if (!d || !d.items) return d?.err ? `<p class="muted zleerr">${esc(d.err)}</p>` : `<div class="zleph" style="--zlen:${n}" aria-busy="true" role="status"><span class="sr">${esc(tr('Loading…'))}</span></div>`;
  if (!d.items.length) return empty;
  return `<ul class="zlel" aria-label="${esc(tr('Recently edited'))}">${/*html-ok*/ d.items.slice(0, n).map(x => zle_rowHtml(x, chip, o)).join('')}</ul>`;
}
// the person's favourites of the area as tiles (favtiles.js): knowledge pages, files and documents
const ZLE_PIN = {wiki: k => k.startsWith('r:wiki:'), ablage: k => k.startsWith('file:') || k.startsWith('doc:'), reading: () => false};
function zle_pinHtml(mod) {
  if (typeof fv2_tiles !== 'function') return '';
  const ts = fv2_tiles().filter(t => !t.sep && (ZLE_PIN[mod] || ZLE_PIN.reading)(t.key));
  return ts.length ? `<section class="zlepin" aria-labelledby="zlepin-h"><h3 id="zlepin-h" class="zleh">${ic('pin', 's')}<span>${esc(tr('Pinned|view'))}</span></h3><div class="fv2bar fv2-page">${ts.map(t => fv2_tileHtml(t, true)).join('')}</div></section>` : '';
}
// the empty state: one sentence and the area's way to add something
function zle_emptyHtml(mod) {
  const btn = mod === 'wiki' ? `<button type="button" class="btn sm pri" data-wk="new">${ic('plus', 's')}${esc(tr('New page'))}</button>`
    : mod === 'ablage' ? `<a class="btn sm pri" href="#${esc(typeof ab_home === 'function' ? ab_home('private') : 'ablage')}">${ic('upload', 's')}${esc(tr('Upload'))}</a>` : '';
  return `<div class="zleempty"><p class="muted">${esc(tr('Nothing edited yet. What you and your team change shows up here.'))}</p>${btn}</div>`;
}
// 2.880.0 (#5561): the overview "All workspaces" of an area: mod 'wiki' | 'ablage' | 'reading'; to / rows as areas.js spo_html
// (rows [[space, name, icon html, html after the name]]: Private, the organisations, Shared with me, the trash). One list of
// rows of one kind: "Recently edited" first (opens #<mod>/recent), then the workspaces; the trash small below it
/** @param {string} mod @param {any} to @param {any[]} rows */
function zle_ovrHtml(mod, to, rows) {
  const row = (href, icon, name, attr, after = '') => `<li><a href="${esc(href)}" class="spovr" ${/*html-ok*/ attr}>${/*html-ok*/ icon}<span>${esc(name)}</span>${/*html-ok*/ after}</a></li>`;
  const trash = rows.find(r => r[0] === 'trash');
  return `<div class="zleov" data-zlemod="${esc(mod)}"><section class="spov zlerows" aria-label="${esc(tr('All workspaces'))}"><ul class="spovl">${/*html-ok*/ row('#' + mod + '/recent', ic('clock', 's'), tr('Recently edited'), 'data-zlego="1"')}${/*html-ok*/ rows.filter(r => r[0] !== 'trash').map(([sp, name, icon, after]) => row(spo_href(to, sp), icon, name, `data-spov="${esc(sp)}"`, after || '')).join('')}</ul></section>${trash ? `<p class="zletrash"><a href="${esc(spo_href(to, 'trash'))}" class="linkbtn" data-spov="trash">${/*html-ok*/ trash[2]}<span>${esc(trash[1])}</span></a></p>` : ''}</div>`;
}
// the page "Recently edited" of an area (#<mod>/recent): the way back, "Pinned", the filter chips, the list. rows as above
// (the filter offers the workspaces of the overview; 'shared' is filtered here from "All", the server knows no such space)
/** @param {string} mod @param {any[]} rows */
function zle_pageHtml(mod, rows) {
  const sps = rows.filter(r => r[0] !== 'trash'), keys = ['all', ...sps.map(r => r[0])];
  const f = keys.includes(ZLE.f[mod]) ? ZLE.f[mod] : 'all';
  const d0 = zle_data(f === 'shared' ? 'all' : f, f === 'shared' ? 50 : ZLE_N);
  const d = f === 'shared' && d0?.items ? {...d0, items: d0.items.filter(x => x.space === 'shared')} : d0;
  const chip = (k, name) => `<button type="button" class="zlefc${k === f ? ' on' : ''}" data-zlef="${esc(k)}" data-zlemod="${esc(mod)}" aria-pressed="${/*html-ok*/ k === f}">${esc(name)}</button>`;
  const chips = sps.length > 1 ? `<div class="zlefs" role="group" aria-label="${esc(tr('Workspaces'))}">${/*html-ok*/ chip('all', tr('All'))}${/*html-ok*/ sps.map(r => chip(r[0], r[1])).join('')}</div>` : '';
  const empty = f === 'all' ? zle_emptyHtml(mod) : `<p class="muted zleempty">${esc(tr('Nothing edited here yet.'))}</p>`;
  return `<div class="zleov zlepage" data-zlemod="${esc(mod)}"><div class="zlehead"><a href="#${esc(mod)}" class="iconbtn" aria-label="${esc(tr('Back'))}" data-navup>${ic('back')}</a><h2>${esc(tr('Recently edited'))}</h2></div>${zle_pinHtml(mod)}${chips}<section class="zlesec" aria-label="${esc(tr('Recently edited'))}">${/*html-ok*/ zle_listHtml(d, ZLE_N, false, empty, {page: true})}</section></div>`;
}
// the start page's block (dashboard.js dashCard): card / slim as there
function zle_homeHtml(card, slim) {
  if (!feat('wiki') && !feat('files') && !feat('reading')) return '';  // none of the three areas on: no block
  const ws = typeof wsCur === 'function' ? wsCur() : 'all', all = ws === 'all' || !wsOn();
  const sp = all ? 'all' : ws, n = !all && ZLE.more ? ZLE_N : ZLE_HOME_N, d = zle_data(sp, n);
  if (d?.items && !d.items.length) return slim(tr('Recently edited: nothing'));
  const ovr = ['wiki', 'ablage', 'reading'].find(m => m === 'wiki' ? feat('wiki') : m === 'ablage' ? typeof ab_on === 'function' && ab_on() : feat('reading'));
  const more = d?.items?.length >= ZLE_HOME_N ? (all ? (ovr ? `<a class="linkbtn hpall" href="#${ovr}/recent">${esc(tr('More'))}</a>` : '') : !ZLE.more ? `<button type="button" class="linkbtn hpall" data-act="zle-more">${esc(tr('More'))}</button>` : '') : '';
  return card(zle_listHtml(d, n, all && wsOn(), '') + more);
}
document.addEventListener('click', e => {
  const fb = /** @type {any} */ (e.target).closest?.('[data-zlef]');
  if (fb) { ZLE.f[fb.dataset.zlemod] = fb.dataset.zlef; renderView(); return; }  // 2.880.0 (#5561): the filter of the page
  if (!/** @type {any} */ (e.target).closest?.('[data-act="zle-more"]')) return;
  ZLE.more = true; renderView();
});
