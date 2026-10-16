// ------------------------------------------------------------------ 2.43.0 (#1452, #1346) widgets changed right in the view
// Every block of a view built with LY (dashboard.js) has a "…" menu: width (a third, half, two thirds, full), height (compact,
// normal, tall), up / down, hide, its settings, "Arrange blocks…" (the list for keyboards and screen readers). On a computer
// a grip at the bottom right resizes a block (snaps to the columns of six and three heights) and its header moves it (a line
// shows where it lands). Phones: one column, only the menu, the height applies. Every change is one undo step.
// "Make this the standard for everyone" / "Reset to the standard" show while my own arrangement differs from the standard
// and (the first) I may set it: the project page = owner / admins of the project, the other views = instance admins
// (accounts/layouts.py; the server checks it). The pin board of the project page (#1346): pinboard.js.
const WG_W = [2, 3, 4, 6];
const WG_WN = [[2, '⅓', N_('A third')], [3, '½', N_('Half')], [4, '⅔', N_('Two thirds')], [6, N_('Full'), N_('Full width')]];
const WG_HN = [[1, N_('Compact')], [2, N_('Normal')], [3, N_('Tall')]];
const WG = {pad: null, mv: null, rs: null};
S.lyStd = null; S.lyStdCan = false;

// ---- the stored value: widths / heights live in opts (lw, lh); the other opts are a block's switches
const wgHasLayout = o => !!(o && (o.order || o.hidden || o.half?.length || o.full?.length || o.mobile || Object.values(o.opts || {}).some(x => x && (x.lw != null || x.lh != null))));
function wgSwitches(opts) {
  const out = {};
  for (const [k, x] of Object.entries(opts || {})) { const y = {...x}; delete y.lw; delete y.lh; if (Object.keys(y).length) out[k] = y; }
  return Object.keys(out).length ? out : null;
}
function wgLayoutOnly(raw) {
  const o = JSON.parse(JSON.stringify(raw || {})), lo = {};
  for (const [k, x] of Object.entries(o.opts || {})) { const y = {}; if (x.lw != null) y.lw = x.lw; if (x.lh != null) y.lh = x.lh; if (Object.keys(y).length) lo[k] = y; }
  if (Object.keys(lo).length) o.opts = lo; else delete o.opts;
  return o;
}
function wgMerge(std, own) {
  const o = wgLayoutOnly(std), sw = wgSwitches(own.opts);
  if (sw) { o.opts ||= {}; for (const [k, x] of Object.entries(sw)) o.opts[k] = {...(o.opts[k] || {}), ...x}; }
  return o;
}
// lyChange: st.ws / st.hs -> opts.lw / lh (only what differs from the block's default) and half / full for 2.42
function wgStoreSizes(bs, st, sz0, ws0, raw) {
  const opts = raw.opts ||= {};
  for (const [k, , , def, , dw] of bs) {
    if (st.sizes[k] !== sz0[k] && st.ws[k] === ws0[k]) st.ws[k] = st.sizes[k] === 'full' ? 6 : (dw || 3);  // the old half / full switch
    const w = st.ws[k], h = st.hs[k], dflt = def === 'full' ? 6 : (dw || 3), x = opts[k] ||= {};
    st.sizes[k] = w >= 4 ? 'full' : 'half';
    if (w === dflt) delete x.lw; else x.lw = w;
    if (h === 2) delete x.lh; else x.lh = h;
    if (!Object.keys(x).length) delete opts[k];
  }
  if (!Object.keys(opts).length) delete raw.opts;
}
// what an arrangement looks like (order, hidden, widths, heights): mine differs from the standard?
function wgSig(v, raw) {
  const p = lyPref(v, {raw, phone: false}), vis = p.order.filter(k => !p.hidden.has(k));
  return JSON.stringify([vis, vis.map(p.w), vis.map(p.h), raw.mobile ? lyPref(v, {raw, phone: true}).order.filter(k => !lyPref(v, {raw, phone: true}).hidden.has(k)) : 0]);
}
const wgJ = s => { try { const o = JSON.parse(s || '{}'); return o && typeof o === 'object' ? o : {}; } catch { return {}; } };

// ---- the standard of the views without a project (GET once, again after a while when a view shows)
function wgStdLoad(force) {
  if (WG.stdBusy || (!force && S.lyStd && Date.now() - (WG.stdAt || 0) < 120000)) return;
  WG.stdBusy = true;
  api('GET', '/api/layouts/std').then(j => {
    const ch = JSON.stringify(j.layouts) !== JSON.stringify(S.lyStd) || !!j.can !== S.lyStdCan;
    S.lyStd = j.layouts || {}; S.lyStdCan = !!j.can; WG.stdAt = Date.now();
    if (ch) viewSafeRender();
  }).catch(() => { WG.stdAt = Date.now(); S.lyStd ||= {}; }).finally(() => { WG.stdBusy = false; });
}

// ---- at the block: "…" and the grip
function wgBlockTools(v, k, b) {
  const nm = tr(b?.[1] || k), desk = !isMobile() && !LY[v].nosize;
  return `<button type="button" class="iconbtn lymore" data-act="wg-more" data-lyv="${v}" data-k="${k}" aria-haspopup="menu" title="${esc(tr('Options: {0}', nm))}" aria-label="${esc(tr('Options: {0}', nm))}">${ic('dots', 's')}</button>${desk ? `<span class="lygrip" data-wggrip="${k}" title="${esc(tr('Drag to resize'))}" aria-hidden="true"></span>` : ''}`;
}
const wgColorCls = (v, k) => { const c = LY[v].color?.(k); return c ? ` lyc lyc-${c}` : ''; };
function wgMoveFn(k, dl) {
  return st => {
    const vis = st.order.filter(x => !st.hidden.has(x)), i = vis.indexOf(k), j = i + dl; if (i < 0 || j < 0 || j >= vis.length) return;
    const a = st.order.indexOf(vis[i]), b = st.order.indexOf(vis[j]); [st.order[a], st.order[b]] = [st.order[b], st.order[a]];
  };
}
function wgMenu(a) {
  const v = a.dataset.lyv, k = a.dataset.k, d = LY[v]; if (!d) return;
  const pr = lyPref(v), b = lyBlocks(v).find(x => x[0] === k); if (!b) return;
  const nm = tr(b[1]), vis = pr.order.filter(x => !pr.hidden.has(x)), i = vis.indexOf(k);
  const set = (fn, msg) => { S.ly.std = false; lydragDo(v, fn, msg); };
  const its = [];
  if (!isMobile() && !d.nosize) its.push({head: tr('Width')}, {row: WG_WN.map(([w, lab, t]) => ({label: tr(lab), title: tr(t), on: pr.w(k) === w, fn: () => set(st => { st.ws[k] = w; }, tr('Width changed'))}))});
  its.push({head: tr('Height')}, {row: WG_HN.map(([h, lab]) => ({label: tr(lab), on: pr.h(k) === h, fn: () => set(st => { st.hs[k] = h; }, tr('Height changed'))}))});
  const col = d.colorItems?.(k) || [];
  if (col.length) its.push({head: tr('Colour')}, {row: col, rcls: 'wgcols', rlab: tr('Colour')});
  its.push('-');
  if (i > 0) its.push({label: tr('Move up'), icon: 'up', fn: () => set(wgMoveFn(k, -1), tr('Moved up'))});
  if (i >= 0 && i < vis.length - 1) its.push({label: tr('Move down'), icon: 'down', fn: () => set(wgMoveFn(k, 1), tr('Moved down'))});
  if (!pr.fixed.has(k)) its.push({label: tr('Hide'), icon: 'eyeoff', fn: () => { set(st => st.hidden.add(k), tr('{0} hidden', nm)); setTimeout(() => $(`#view [data-act="ly-add"][data-lyv="${v}"]`)?.focus(), 30); }});
  const more = [...lyo_items(v, k, a), ...(d.blockItems?.(k) || [])];  // 2.55.0 (#1065): the block's settings
  if (more.length) its.push('-', ...more);
  its.push('-', {label: tr('Arrange blocks…'), icon: 'sliders', fn: () => lyOpen(v, true)});
  menu(a, its, null, null, nm);
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="wg-"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act;
  if (k === 'wg-more') wgMenu(a);
  else if (k === 'wg-promote') lyQueue(() => wgPromote(a.dataset.lyv));  // after the saves still on their way
  else if (k === 'wg-hide') wgHide(a.dataset.lyv);
  else if (k === 'wg-reset') lyQueue(() => wgReset(a.dataset.lyv));
}, true);

// ---- "Make this the standard for everyone" / "Reset to the standard"
function wgOwn(v) {  // {own, std} raw values (the project page: mine / the project's standard)
  const d = LY[v];
  if (d.src) { const y = S.povD[routeList()?.id]?.j?.layout || {}; return {own: y.mine ? wgJ(y.mine) : null, std: wgJ(y.std)}; }
  const o = wgJ(LY_PEND[d.key] ?? S.settings?.[d.key]);
  const sd = wgJ(S.lyStd?.[d.key]);
  return {own: wgHasLayout(o) ? o : null, std: wgHasLayout(sd) || !d.def ? sd : d.def()};  // 2.45.0 (#1504): no standard set = the view's default
}
// 2.46.2 (#1726): the note can be dismissed; it stays away until the own arrangement or the standard changes (setting wgstd_hide, all devices)
const wgHideKey = v => LY[v]?.src ? (routeList()?.id ? v + ':' + routeList().id : '') : v;
const wgHideMap = () => wgJ(S.settings?.wgstd_hide);
function wgHideSig(v, own, std) {
  const t = wgSig(v, own) + '|' + wgSig(v, std); let h = 5381;
  for (let i = 0; i < t.length; i++) h = ((h * 33) ^ t.charCodeAt(i)) >>> 0;
  return h.toString(36) + t.length.toString(36);
}
function wgHide(v) {
  const hk = wgHideKey(v), {own, std} = wgOwn(v); if (!hk || !own) return;
  const m = wgHideMap(); m[hk] = wgHideSig(v, own, std);
  const keys = Object.keys(m); if (keys.length > 150) for (const k of keys.slice(0, keys.length - 150)) delete m[k];
  S.settings.wgstd_hide = JSON.stringify(m); renderView();
  api('PATCH', '/api/settings', {wgstd_hide: S.settings.wgstd_hide}).catch(() => { /* api() said it; the local value stays */ });
}
function wgStdBar(v, o) {
  const d = LY[v]; if (S.ly.view === v) return '';
  if (!d.src) setTimeout(() => wgStdLoad(), 0);
  const {own, std} = wgOwn(v);
  if (!own || wgSig(v, own) === wgSig(v, std)) return '';
  const hk = wgHideKey(v), hs = wgHideSig(v, own, std);
  if (hk && wgHideMap()[hk] === hs) return '';  // 2.46.2 (#1726): dismissed for exactly this arrangement and standard
  const can = d.src ? !!o.canStd : S.lyStdCan;
  return `<div class="wgstd"><span class="muted">${tr('Your own arrangement differs from the standard.')}</span><span class="spacer"></span>${can ? `<button type="button" class="btn sm" data-act="wg-promote" data-lyv="${v}">${ic('users', 's')}<span>${tr('Make this the standard for everyone')}</span></button>` : ''}<button type="button" class="btn sm" data-act="wg-reset" data-lyv="${v}">${ic('undo', 's')}<span>${tr('Reset to the standard')}</span></button><button type="button" class="iconbtn wgstdx" data-act="wg-hide" data-lyv="${v}" title="${esc(tr('Hide this note'))}" aria-label="${esc(tr('Hide this note'))}">${ic('x', 's')}</button></div>`;
}
const wgStr = o => o && Object.keys(o).length ? JSON.stringify(o) : '';
async function wgPromote(v) {
  const d = LY[v];
  if (d.src) {
    const l = routeList(), dd = l && S.povD[l.id], y = dd?.j?.layout; if (!y) return;
    const put = async (std, mine) => { await api('PUT', `/api/lists/${l.id}/layout`, {layout: std, scope: 'standard'}); const r = await api('PUT', `/api/lists/${l.id}/layout`, {layout: mine, scope: 'mine'}); if (dd.j) { dd.j.layout = r; renderView(); } return {}; };
    const old = {std: y.std, mine: y.mine};
    try { const r = await api('PUT', `/api/lists/${l.id}/layout`, {layout: y.mine, scope: 'promote'}); dd.j.layout = r; renderView(); } catch { return; }
    const e = histAdd({label: tr('Standard changed'), undo: () => put(old.std, old.mine), redo: async () => { const r = await api('PUT', `/api/lists/${l.id}/layout`, {layout: old.mine, scope: 'promote'}); if (dd.j) { dd.j.layout = r; renderView(); } return {}; }});
    histToast(tr('This is the standard for everyone in the project now'), e);
    return;
  }
  const raw = wgJ(LY_PEND[d.key] ?? S.settings?.[d.key]), oldStd = S.lyStd?.[d.key] || '', oldOwn = wgStr(raw);
  const go = async (std, own) => { const j = await api('PUT', `/api/layouts/std/${d.key}`, {layout: std}); S.lyStd = j.layouts; S.settings[d.key] = own; lyPatch(d.key, own); renderView(); return {}; };
  const sw = wgSwitches(raw.opts), newStd = wgStr(wgLayoutOnly(raw)), newOwn = sw ? JSON.stringify({opts: sw}) : '';
  try { await go(newStd, newOwn); } catch { return; }
  const e = histAdd({label: tr('Standard changed'), undo: () => go(oldStd, oldOwn), redo: () => go(newStd, newOwn)});
  histToast(tr('This is the standard for everyone now'), e);
}
function wgReset(v) {
  const d = LY[v];
  if (d.src) {
    const l = routeList(), y = l && S.povD[l.id]?.j?.layout; if (!y) return;
    const old = y.mine, put = s => () => { LY.project.save(s, false); return {}; };
    LY.project.save('', false);
    histToast(tr('Back to the standard'), histAdd({label: tr('Back to the standard'), undo: put(old), redo: put('')}));
    return;
  }
  const old = wgStr(wgJ(LY_PEND[d.key] ?? S.settings?.[d.key])), sw = wgSwitches(wgJ(old).opts), nw = sw ? JSON.stringify({opts: sw}) : '';
  const put = s => () => { S.settings[d.key] = s; lyPatch(d.key, s); renderView(); return {}; };
  put(nw)();
  histToast(tr('Back to the standard'), histAdd({label: tr('Back to the standard'), undo: put(old), redo: put(nw)}));
}

// ---- a computer: the grip resizes (snaps to the columns of six and three heights), the header moves the block
function wgGridCols(grid) { return wgCols(grid) ? 6 : getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length || 1; }
// 2.45.0 (#1504): the start page's two columns (dashboard.js lyHtml): a block sits in .hpcol inside the grid; the columns
// count while they show as columns (narrower screens: display:contents, the plain grid)
const wgGrid = el => el.parentElement?.classList.contains('hpcol') ? el.parentElement.parentElement : el.parentElement;
const wgCols = grid => grid?.classList.contains('hpcols') && getComputedStyle(grid.firstElementChild).display !== 'contents';
document.addEventListener('pointerdown', e => {
  if (e.pointerType === 'touch' || e.button !== 0 || S.ly.view) return;
  const g = e.target.closest?.('.lysix > .lyb > .lygrip, .lysix > .hpcol > .lyb > .lygrip');
  if (g) {
    const el = g.parentElement, grid = wgGrid(el), v = grid.dataset.ly, k = el.dataset.lyk, pr = lyPref(v), r = el.getBoundingClientRect();
    if (wgGridCols(grid) < 6) return;
    e.preventDefault();
    WG.rs = {el, v, k, x0: e.clientX, y0: e.clientY, w0: r.width, left: r.left, w: pr.w(k), h: pr.h(k), w1: pr.w(k), h1: pr.h(k), col: (grid.clientWidth + parseFloat(getComputedStyle(grid).columnGap || 0)) / 6};
    document.body.classList.add('wgresizing');
    return;
  }
  const hd = e.target.closest?.('.lysix > .lym .povh, .lysix > .lym > .dcard > h3, .lysix > .lym > .dcard > h2, .lysix > .lym > section > h2, .lysix > .lym > section > h3, .lysix > .hpcol > .lym > .dcard > h3');
  if (!hd || e.target.closest('a,button,input,textarea,select,label,[contenteditable]')) return;
  const el = hd.closest('.lyb');
  if (el.closest('.lysix') !== wgGrid(el)) return;
  WG.mv = {el, grid: wgGrid(el), v: wgGrid(el).dataset.ly, k: el.dataset.lyk, x0: e.clientX, y0: e.clientY, active: false};
});
document.addEventListener('pointermove', e => {
  const rs = WG.rs;
  if (rs) {
    const span = Math.max(1, Math.round((e.clientX - rs.left) / rs.col)), w = WG_W.reduce((b, x) => Math.abs(x - span) < Math.abs(b - span) ? x : b, 6);
    const h = Math.min(3, Math.max(1, rs.h + Math.round((e.clientY - rs.y0) / 140)));
    if (w !== rs.w1 || h !== rs.h1) { rs.el.classList.remove('lw' + rs.w1, 'lh' + rs.h1); rs.el.classList.add('lw' + w, 'lh' + h); rs.w1 = w; rs.h1 = h; }
    return;
  }
  const mv = WG.mv; if (!mv) return;
  if (!mv.active) { if (Math.hypot(e.clientX - mv.x0, e.clientY - mv.y0) < 6) return; mv.active = true; mv.el.classList.add('wgdrag'); document.body.classList.add('wgmoving'); mv.line = document.createElement('div'); mv.line.className = 'wgline'; document.body.appendChild(mv.line); }
  e.preventDefault();
  const t = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('.lyb');
  if (!t || wgGrid(t) !== mv.grid || t === mv.el) { mv.to = null; mv.line.hidden = true; return; }
  const r = t.getBoundingClientRect(), wide = r.width > mv.grid.clientWidth * .75 || wgCols(mv.grid), after = wide ? e.clientY > r.top + r.height / 2 : e.clientX > r.left + r.width / 2;
  mv.to = t.dataset.lyk; mv.after = after; mv.line.hidden = false;
  mv.line.style.cssText = wide ? `left:${r.left}px;width:${r.width}px;top:${(after ? r.bottom : r.top) - 2}px;height:3px` : `top:${r.top}px;height:${r.height}px;left:${(after ? r.right : r.left) - 2}px;width:3px`;
});
function wgPointerEnd(cancel) {
  const rs = WG.rs; WG.rs = null;
  if (rs) {
    document.body.classList.remove('wgresizing');
    if (cancel || (rs.w1 === rs.w && rs.h1 === rs.h)) { if (cancel) renderView(); return; }
    lydragDo(rs.v, st => { st.ws[rs.k] = rs.w1; st.hs[rs.k] = rs.h1; }, tr('Size changed'));
    return;
  }
  const mv = WG.mv; WG.mv = null; if (!mv?.active) return;
  mv.line?.remove(); mv.el.classList.remove('wgdrag'); document.body.classList.remove('wgmoving');
  if (cancel || !mv.to) return;
  const keys = $$(':scope > .lyb, :scope > .hpcol > .lyb', mv.grid).sort((a, b) => (+a.style.order || 0) - (+b.style.order || 0)).map(x => x.dataset.lyk).filter(x => x !== mv.k);
  keys.splice(keys.indexOf(mv.to) + (mv.after ? 1 : 0), 0, mv.k);
  const nm = lyBlocks(mv.v).find(b => b[0] === mv.k)?.[1];
  lydragDo(mv.v, lydragOrder(mv.v, keys), tr('{0} moved', tr(nm || '')));
}
document.addEventListener('pointerup', () => wgPointerEnd(false));
document.addEventListener('pointercancel', () => wgPointerEnd(true));
document.addEventListener('keydown', e => { if (e.key === 'Escape' && (WG.rs || WG.mv?.active)) { e.preventDefault(); e.stopPropagation(); wgPointerEnd(true); } }, true);

