/* Kalmido web client: themes, header strips of lists and folders, small moments (2.83.0 C, #1427).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- themes (Settings > Appearance, per device like the rest of the appearance): a theme is a preset over the single
// settings. LOOK.pack (icons.js) holds the names, app.css the background tones and the card style per theme
// (:root[data-pack=...], scoped to the colour scheme a theme is made for). Picking Paper switches to the light scheme,
// Night to the dark one; Control room (the default) and High contrast keep the scheme. Accent, density, font stay.
const O3C_PACK_SCHEME = {paper: 'light', night: 'dark'};
// [background, raised background, text, line] of the small preview of each theme in the picker
const O3C_PACK_PV = {control: ['#0f1012', '#1e2024', '#eeeef0', '#2a2c31'], paper: ['#fbf8f2', '#efe9de', '#1f1a13', '#ddd3c2'],
  night: ['#0b1020', '#19223d', '#e8ecf6', '#27324f'], contrast: ['#000000', '#161616', '#ffffff', '#8a8a8a']};
const O3C_META = {paper: ['#f5f0e7', null], night: [null, '#111830'], contrast: ['#ffffff', '#0a0a0a']};  // theme-color [light, dark]
const o3c_light = () => { const t = document.documentElement.dataset.theme; return t === 'light' || (t === 'auto' && matchMedia('(prefers-color-scheme: light)').matches); };
function o3c_meta() {  // the browser / app bar colour follows the theme (applyTheme sets the default)
  const m = document.querySelector('meta[name="theme-color"]'), c = O3C_META[lookPref('pack')]?.[o3c_light() ? 0 : 1];
  if (m && c) m.content = c;
}
o3c_meta();
try { matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => setTimeout(o3c_meta, 0)); } catch { /* old browser */ }
function o3c_packHtml() {
  const cur = lookPref('pack');
  return `<h4>${tr('Theme')}<span class="devtag">${tr('This device')}</span></h4>
    <div class="lkopts o3c-packs" id="s-pack" role="group">${LOOK.pack.map(([v, n]) => { const [bg, bg3, tx, ln] = O3C_PACK_PV[v];
      return `<button type="button" data-look="pack" data-v="${v}" aria-pressed="${cur === v}" class="${cur === v ? 'on' : ''}"><span class="o3c-pv" aria-hidden="true" style="--pb:${bg};--pb3:${bg3};--pt:${tx};--pl:${ln}"><i></i><i></i><i></i></span><span class="lkn">${tr(n)}</span></button>`; }).join('')}</div>
    <div class="shint">${tr('A theme sets the background tones and the look of cards. Paper switches to the light scheme, Night to the dark one; your accent colour, density and font stay.')}</div>`;
}
// a click on a theme (settings.js): theme + colour scheme as ONE undo step
function o3c_packPick(md, v) {
  if (!LOOK.pack.some(x => x[0] === v)) return;
  const get = () => ({pack: LS.get('pack', null), theme: LS.get('theme', null)});
  const put = o => {
    for (const k of ['pack', 'theme']) { if (o[k] != null) LS.set(k, o[k]); else LS.del(k); }
    applyTheme(); applyLook(); o3c_meta();
    if (md) lookRedraw(md, `[data-look="pack"][data-v="${lookPref('pack')}"]`);
  };
  const cur = get();
  setLocal(tr('Theme'), get, put, {pack: v === LOOK.pack[0][0] ? null : v, theme: O3C_PACK_SCHEME[v] || cur.theme});
}
// ---- device switch: header pictures (on by default; only "off" is stored)
const o3c_headOn = () => LS.get('headShow', true) !== false;
// 2.118.0 (#2297): the rings follow the account switch side_progress (one switch for line and ring, all devices)
const o3c_ringsOn = () => S.settings?.side_progress !== '0';
// a device that had the old rings switch off hands it to the account once, then forgets the key
function o3c_ringsMigrate() {
  if (LS.get('rings', true) !== false) return;
  if (!S.settings || S.settings.side_progress === '0') { LS.del('rings'); return; }
  S.settings.side_progress = '0';  // the device key goes only once the account holds the value (offline: next load tries again)
  api('PATCH', '/api/settings', {side_progress: '0'}).then(() => LS.del('rings')).catch(() => {});
}
function o3c_lookHtml() {
  return `<h4>${tr('Lists')}</h4>
    <div class="row"><label class="chkl"><input type="checkbox" id="s-o3c-head" ${o3c_headOn() ? 'checked' : ''}> ${tr('Show header pictures')}</label></div>
    <div class="shint">${tr('The header of a list or folder is set in its settings and is the same for everyone. Here you only choose whether this device shows it.')}</div>`;
}
document.addEventListener('change', e => {
  const k = {'s-o3c-head': 'headShow'}[e.target?.id]; if (!k) return;
  e.stopPropagation();
  setLocal(tr('Show header pictures'), () => LS.get(k, true) !== false,
    on => { if (on) LS.del(k); else LS.set(k, false); const c = document.getElementById(e.target.id); if (c) c.checked = on; render(); }, e.target.checked);
}, true);

// ---- header strips: a slim band between the header and the view of a list (or an owner's folder): a gradient from the
// list colour, a CSS pattern or the list's own picture. Decorative (aria-hidden), never in the way of the content.
const O3C_STYLES = [['', N_('None|header')], ['gradient', N_('Gradient')], ['dots', N_('Dots')], ['lines', N_('Lines')], ['grid', N_('Grid')]];
let O3C_FH = null;  // my folders' strips {folder: style}, loaded once when a folder view opens
async function o3c_fhLoad() { try { O3C_FH = (await api('GET', '/api/folder-heads')).heads || {}; } catch { O3C_FH = {}; } o3c_sync(); }
function o3c_target() {
  const k = S.route?.mod === 'tasks' ? String(S.route.key || '') : '';
  if (k.startsWith('l:')) { const l = listById(+k.slice(2)); return l ? {l, st: l.header_style || ''} : null; }
  if (k.startsWith('folder:')) {
    if (O3C_FH === null) { O3C_FH = {}; o3c_fhLoad(); }
    const f = k.slice(7), c = typeof lp_folderCols === 'function' ? lp_folderCols()[f] : '';
    return {f, st: O3C_FH[f] || '', c};
  }
  return null;
}
const o3c_img = l => l && l.header_style === 'image' && l.header_file && !l.e2e ? `/api/list-header/${l.id}/${encodeURIComponent(l.header_file)}.jpg` : '';
function o3c_sync() {
  const main = $('#main'), view = $('#view'); if (!main || !view) return;
  const t = o3c_target(), st = t && o3c_headOn() ? t.st : '', img = st === 'image' ? o3c_img(t.l) : '';
  let el = $('#o3c-head');
  if (!st || (st === 'image' && !img)) { el?.remove(); o3c_tickAfter(); return; }
  if (!el) { el = document.createElement('div'); el.id = 'o3c-head'; el.setAttribute('aria-hidden', 'true'); }
  if (el.nextElementSibling !== view) main.insertBefore(el, view);
  const cls = 'o3c-head o3c-h-' + st; if (el.className !== cls) el.className = cls;
  const bg = img ? `url("${img}")` : ''; if (el.dataset.img !== bg) { el.dataset.img = bg; el.style.backgroundImage = bg; }
  const c = t.c && typeof lp_near === 'function' ? lp_near(t.c) : null;  // a folder: its colour (a list: the list accent of #main)
  if (c) { el.style.setProperty('--o3c-d', c[2]); el.style.setProperty('--o3c-l', c[4]); } else { el.style.removeProperty('--o3c-d'); el.style.removeProperty('--o3c-l'); }
  o3c_tickAfter();
}
// the row in the list dialog (dialogs.js listModal): owner + list admins; a locked list gets no own picture
function o3c_rowHtml(l) {
  if (!l || l.is_inbox || !canManage(l)) return '';
  const cur = l.header_style || '', pic = !l.e2e;
  const b = (v, n) => `<button type="button" data-o3ch="${v}" aria-pressed="${cur === v}" class="${cur === v ? 'on' : ''}">${tr(n)}</button>`;
  return `<div class="row o3c-hrow" id="l-o3c"><label>${tr('Header')}</label><div class="seg wrap" role="group" aria-label="${esc(tr('Header'))}">${O3C_STYLES.map(([v, n]) => b(v, n)).join('')}${pic && l.header_file ? b('image', N_('Picture')) : ''}${pic ? `<button type="button" data-o3cup="1">${ic('picture', 's')} ${l.header_file ? tr('Other picture…') : tr('Picture…')}</button>` : ''}</div>
    <input type="file" id="l-o3c-file" accept="image/jpeg,image/png,image/webp" hidden></div>
    <div class="shint lhint">${tr('A slim band on top of the list, the same for everyone in it. A picture: JPEG, PNG or WebP, at most 2 MB.')}</div>`;
}
function o3c_wire(md, id) {
  const box = $('#l-o3c', md); if (!box) return;
  const redraw = () => { const l = listById(id), old = $('#l-o3c', md); if (!l || !old) return; const t = document.createElement('div'); t.innerHTML = o3c_rowHtml(l); const nw = t.querySelector('#l-o3c'); if (nw) { old.replaceWith(nw); o3c_wire(md, id); } };
  box.addEventListener('click', e => {
    const b = e.target.closest('[data-o3ch], [data-o3cup]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    if (b.dataset.o3cup) { $('#l-o3c-file', md)?.click(); return; }
    o3c_setStyle(id, b.dataset.o3ch).then(redraw);
  });
  $('#l-o3c-file', md)?.addEventListener('change', e => {
    e.stopPropagation(); const f = e.target.files?.[0]; e.target.value = ''; if (!f) return;
    if (f.size > 2 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 2)); return; }
    o3c_upload(id, f).then(redraw);
  });
}
async function o3c_put(id, st) {
  const j = await api('PUT', `/api/lists/${id}/header`, {style: st});
  const l = listById(id); if (l) Object.assign(l, {header_style: j.header_style, header_file: j.header_file});
  render();
}
// one undo step per change (back to the strip before)
function o3c_undo(id, was, now) {
  offerUndo(tr('Header changed'), histAdd({label: tr('Header'),
    undo: async () => { await o3c_put(id, was); return {skipped: []}; }, redo: async () => { await o3c_put(id, now); return {skipped: []}; }}));
}
async function o3c_setStyle(id, st) {
  const l = listById(id); if (!l) return;
  const was = l.header_style || '';
  if (was === st) return;
  try { await o3c_put(id, st); } catch { return; }
  o3c_undo(id, was, st);
}
async function o3c_upload(id, f) {
  const l = listById(id); if (!l) return;
  const was = l.header_style || '', fd = new FormData(); fd.append('file', f, f.name || 'header.jpg');
  let j; try { j = await api('POST', `/api/lists/${id}/header`, fd); } catch { return; }
  Object.assign(l, {header_style: j.header_style, header_file: j.header_file}); render();
  o3c_undo(id, was === 'image' ? '' : was, 'image');  // the old picture is replaced: undo goes back to no picture
}
// a folder's strip (sidebar folder menu): the style only, mine
function o3c_folderMenuRow(f) { return [{label: tr('Header…'), icon: 'picture', fn: () => o3c_folderPick(f)}]; }
async function o3c_folderPick(f) {
  if (O3C_FH === null) { O3C_FH = {}; await o3c_fhLoad(); }
  const cur = O3C_FH[f] || '', anchor = $(`.fhead[data-folder="${CSS.escape(f)}"]`) || $('#side');
  menu(anchor, O3C_STYLES.map(([v, n]) => ({label: tr(n), on: v === cur, fn: () => o3c_folderSet(f, v, true)})), null, null, tr('Header'));
}
async function o3c_folderSet(f, st, undo) {
  const was = O3C_FH?.[f] || '';
  if (was === st) return;
  try { O3C_FH = (await api('PUT', '/api/folder-heads', {folder: f, style: st})).heads || {}; } catch { return; }
  o3c_sync();
  if (undo) offerUndo(tr('Header changed'), histAdd({label: tr('Header'),
    undo: async () => { await o3c_folderSet(f, was, false); return {skipped: []}; }, redo: async () => { await o3c_folderSet(f, st, false); return {skipped: []}; }}));
}

// ---- small moments
// ticking off: the circle pops softly (transform / opacity, 350 ms, #2163; app.css turns it off with prefers-reduced-motion).
// The row is often drawn anew right after the click: the mark is set on the click and once more on the next render.
let o3c_tick = null;  // {id, at}
document.addEventListener('click', e => {
  const k = e.target.closest?.('#view .trow[data-id] .chk'); if (!k) return;
  const r = k.closest('.trow'); if (r.classList.contains('done')) return;
  o3c_tick = {id: r.dataset.id, at: Date.now()}; k.classList.add('o3c-pop');
}, true);
function o3c_tickAfter() {
  if (!o3c_tick || Date.now() - o3c_tick.at > 600) { o3c_tick = null; return; }
  $(`#view .trow[data-id="${o3c_tick.id}"] .chk`)?.classList.add('o3c-pop');
}
// empty pages (an empty list, an empty Today): 2.136.0 (#2193): the bot figure (calm, or happy when Today is done)
// instead of the Kalmido K line drawing of 2.83.0
const o3c_empty = (title, sub = '', st = 'ruhig') => `<div class="empty hempty o3c-empty">${botFig(st)}<b>${esc(title)}</b>${sub ? `<span>${esc(sub)}</span>` : ''}</div>`;
// progress rings in the sidebar: done / all of the list's tasks (the numbers the state already brings, list.progress);
// not where a project shows its progress bar, not for the inbox
function o3c_ring(l, bar) {
  const p = l?.progress; if (bar || !o3c_ringsOn() || !p || !(p.total > 0) || l.is_inbox) return '';
  const v = Math.max(0, Math.min(100, Math.round(p.done / p.total * 100))), lab = tr('{0} of {1} done ({2}%)', p.done, p.total, v);
  return `<span class="o3c-ring" role="img" style="--p:${v}" aria-label="${esc(lab)}" title="${esc(lab)}"></span>`;
}
