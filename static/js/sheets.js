/* Kalmido web client: tables (2.89.0, #1916 part B), "Excel in simple" with Kalmido variables. Route #sheets (the sheets of
   the current space, grouped Private / organisations), #sheets/<id> (one sheet) and #sheets/l/<list id> (the sheets attached
   to a project or list; "New table" there attaches it). A sheet has columns (text, number, currency, percent, date, selection
   with coloured options for the cell or the whole row), rows and cells holding an own value or a formula (=…). The server
   computes every cell for the viewer (kalmido/sheets, his visibility; formulas are stored with ids and shown with names).
   Keys like a spreadsheet (arrows, Enter, Tab, Esc, Delete, F2, copy / paste of ranges, Shift for a range), a formula bar,
   suggestions after "=" (GET …/vars), a click on a cell while writing a formula inserts its address. Names and formulas show
   on hover (desktop) or a long press (phone). The colour of a cell tells where its value comes from (own, formula, Kalmido
   in the accent, frozen grey), errors say why ("Source deleted" + the last value this viewer saw, "No access", …). The panel
   shows the cell's name, formula, "Comes from" / "Goes into", freeze, the Kalmido sources of the sheet and the agents'
   changes (each call taken back at once); arrows show the dependencies. Sorting is saved, filtering is a view only.
   Every action is one Undo step. Live: the area "sheets" of /api/version (liveparts.js -> shvLive), any other change of the
   state (Kalmido values follow tasks and times) and every 10 s while Kalmido values or other editors are in the sheet; the
   cell being edited is never overwritten. Parts C / D add menu entries through SHV_HOOKS.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const SHV = {idx: {}, sh: null, err: '', errFor: null, busy: {}, cur: null, anc: null, ed: null, filt: {}, deps: 0, ac: null, acT: 0,
  drag: null, lp: null, lpDone: 0, newSp: '', stale: false, tick: 0, presAt: 0};
// 2.89.0 (#1916): parts C / D: menu: [(sheet) -> items] (the sheet's "…" menu), overview: [(space, lid) -> items] (the overview's "…");
// a var on window, so entries registered by a script that ran before this one stay
var SHV_HOOKS = window.SHV_HOOKS || {};
SHV_HOOKS.menu = SHV_HOOKS.menu || []; SHV_HOOKS.overview = SHV_HOOKS.overview || [];
const SHV_KINDS = [['text', N_('Text')], ['number', N_('Number')], ['currency', N_('Currency')], ['percent', N_('Percent')], ['date', N_('Date')], ['select', N_('Selection')]];
const SHV_NUM = ['number', 'currency', 'percent'];
const SHV_KICON = {text: 'edit', number: 'hash', currency: 'money', percent: 'chart', date: 'cal', select: 'list'};
const SHV_ERR = {deleted: N_('Source deleted'), denied: N_('No access'), cycle: N_('Circular reference'), syntax: N_('Formula error'),
  div0: N_('Division by zero'), ref: N_('Reference missing'), type: N_('Wrong type'), na: N_('Not found')}; // 2.124.0 A (#2109): + na
const SHV_ORIGIN = {own: N_('Own value'), formula: N_('Formula'), kalmido: N_('Value from Kalmido'), frozen: N_('Frozen value')};
const SHV_WIDTHS = [[80, N_('Narrow')], [120, N_('Normal')], [200, N_('Wide')], [320, N_('Very wide')]];

const shvSpaces = () => ['private', ...(S.me?.workspaces || []).map(w => 'org:' + w.id)];
const shvSpaceName = sp => sp === 'private' ? tr('Private|workspace') : sp === 'shared' ? tr('Shared with me') : (wsOrg(sp.slice(4))?.name || tr('Organisation'));  // 2.124.0 C (#2113): + shared
const shvListSpace = l => l?.org_id ? 'org:' + l.org_id : 'private';
function shvNewSpace() {  // the space a new sheet goes to: the workspace switch, else the last one used, else the first organisation
  const ok = v => !!v && shvSpaces().includes(v), ws = typeof wsCur === 'function' ? wsCur() : 'all';
  if (ws && ws !== 'all' && ok(ws)) return ws;
  const ls = LS.get('shvSpace', ''); if (ok(ls)) return ls;
  return shvSpaces()[1] || 'private';
}

// ---- loading
async function shvLoadIdx(key, force) {
  const d = SHV.idx[key] || (SHV.idx[key] = {});
  if (SHV.busy['i' + key] || (!force && d.items && d.v === S.v)) return;
  SHV.busy['i' + key] = true;
  try { const j = await rawFetch('GET', '/api/sheets?' + (key.startsWith('l:') ? 'list_id=' + +key.slice(2) : 'space=all')); d.items = j.sheets || []; d.err = ''; }
  catch (e) { if (e.message === 'auth') return; d.err = e instanceof Offline ? tr('Tables are only available online.') : e.message; }
  finally { d.v = S.v; SHV.busy['i' + key] = false; }
  if (S.route.mod === 'sheets') viewSafeRender();
  if (key === 'all' && typeof sbb_sync === 'function') sbb_sync('sheets');  // 2.152.3 B (#2619): the panel
}
// 2.126.2 A (#2357): the pages that link this table ([[tabelle:…]]), asked once per opening (not on every cell change)
const SHV_REFS = {id: 0, pages: []};
async function shvRefs(id) {
  if (SHV_REFS.id === id) return;
  SHV_REFS.id = id; SHV_REFS.pages = [];
  let ps; try { ps = (await rawFetch('GET', '/api/wiki/refs?sheet=' + id)).pages || []; } catch { return; }
  if (SHV_REFS.id !== id || !ps.length) return;
  SHV_REFS.pages = ps;
  if (S.route.mod === 'sheets' && S.route.sh === id) shvRender();
}
function shvRefsHtml(sh) {
  const ps = SHV_REFS.id === sh.id ? SHV_REFS.pages : [];
  return ps.length ? `<div class="dsec wkmen shvmen">${ic('book', 's')}<span class="muted">${tr('Mentioned in')}</span>${ps.map(p => `<a href="#wiki/${p.id}">${esc(p.path)}</a>`).join('<span class="muted">,</span>')}</div>` : '';
}
async function shvLoad(id, force) {
  if (SHV.busy['s' + id]) { SHV.again = true; return; }
  if (!force && SHV.sh && SHV.sh.id === id && SHV.sh._v === S.v) return;
  SHV.busy['s' + id] = true;
  let changed = false;
  try {
    const sh = await rawFetch('GET', '/api/sheets/' + id);
    if (SHV.sh?.id !== id) { SHV.cur = SHV.anc = null; SHV.ed = null; }
    changed = !SHV.sh || SHV.sh.id !== id || SHV.sh.rev !== sh.rev || JSON.stringify(SHV.sh.presence || []) !== JSON.stringify(sh.presence || []) || shvKalSig(SHV.sh) !== shvKalSig(sh);
    shvPrep(sh); sh._v = S.v; SHV.sh = sh; SHV.err = ''; SHV.errFor = null;
    shvRefs(id);
  } catch (e) {
    if (e.message === 'auth') return;
    SHV.errFor = id + ':' + S.v; changed = true;
    SHV.err = e.status === 404 || e.status === 403 ? tr('This table does not exist or you cannot see it.') : e instanceof Offline ? tr('Tables are only available online.') : e.message;
    if (SHV.sh?.id === id) SHV.sh = null;
  } finally { SHV.busy['s' + id] = false; }
  // 2.98.0 C (#2181): the load asked for meanwhile runs, and this load's change is still drawn (the second load found
  // nothing new and drew nothing: a table opened while a draw asked for it again stayed on "Loading…")
  if (SHV.again) { SHV.again = false; await shvLoad(id, true); }
  if (S.route.mod === 'sheets' && S.route.sh === id && changed) shvRender();
}
const shvKalSig = sh => (sh?.cells || []).filter(c => c.origin === 'kalmido' || c.error).map(c => c.id + '=' + c.display + c.error).join('|');
function shvPrep(sh) {  // indexes of a loaded sheet
  sh.columns = (sh.columns || []).slice().sort((a, b) => a.pos - b.pos);
  sh.rows = (sh.rows || []).slice().sort((a, b) => a.pos - b.pos);
  sh._col = new Map(sh.columns.map(c => [c.id, c]));
  sh._rowNo = new Map(sh.rows.map((r, i) => [r.id, i + 1]));
  sh._at = new Map(); sh._id = new Map(); sh._into = new Map();
  for (const c of sh.cells || []) { sh._at.set(c.row_id + ':' + c.col_id, c); sh._id.set(c.id, c); }
  for (const c of sh.cells || []) for (const r of c.refs || []) { if (!sh._into.has(r)) sh._into.set(r, []); sh._into.get(r).push(c.id); }
  // the sources overview from the cells (as the server builds it), so an own write updates it without a reload
  const src = new Map();
  for (const c of sh.cells || []) for (const x of c.sources || []) {
    const k = x.type + ':' + x.id; if (!src.has(k)) src.set(k, {type: x.type, id: x.id, label: x.label, fields: [], denied: x.denied, deleted: x.deleted});
    if (!src.get(k).fields.includes(x.field)) src.get(k).fields.push(x.field);
  }
  sh.sources = [...src.values()];
  sh._kal = (sh.cells || []).some(c => c.origin === 'kalmido' || (c.sources || []).length || c.error === 'deleted' || c.error === 'denied');
}
const shvCell = (r, c, sh = SHV.sh) => sh?._at.get(r + ':' + c) || null;
const shvAddr = (r, c, sh = SHV.sh) => (sh?._col.get(c)?.letter || '?') + (sh?._rowNo.get(r) || '?');
const shvOthers = (sh = SHV.sh) => (sh?.presence || []).filter(p => p.user_id !== S.me?.id);
function shvRender() {  // a redraw of the open sheet (the grid's own focus and an open editor stay)
  if (S.route.mod !== 'sheets') return;
  if (SHV.ed) { SHV.stale = true; shvPatchAll(); return; }
  SHV.stale = false;
  viewSafeRender();
  requestAnimationFrame(shvAfter);
}
function shvLive() {  // liveparts.js: the area "sheets" moved
  if (S.route.mod !== 'sheets') { for (const d of Object.values(SHV.idx)) d.v = -1; return; }
  if (S.route.sh) { if (SHV.ed) SHV.stale = true; else shvLoad(S.route.sh, true); }
  else { for (const d of Object.values(SHV.idx)) d.v = -1; viewSafeRender(); }
  if (typeof sbb_sync === 'function') { if (SHV.idx.all) SHV.idx.all.v = -1; SHF.v = -1; sbb_sync('sheets'); }  // 2.152.3 B (#2619): the panel (renamed / new / deleted elsewhere); 2.199.0 C: + folders
}
// every 10 s while the sheet has Kalmido values or someone else in it (else every 30 s, for the "is editing" notice); while
// a cell is edited only the own presence is renewed
setInterval(() => {
  if (S.route.mod !== 'sheets' || !S.route.sh || document.hidden || !SHV.sh || SHV.sh.id !== S.route.sh) return;
  if (SHV.ed) { shvPresence(SHV.ed); return; }
  SHV.tick++;
  if (SHV.sh._kal || shvOthers().length || SHV.tick % 3 === 0) shvLoad(S.route.sh, true);
}, 10000);
function shvPresence(ed) {
  const sh = SHV.sh; if (!sh || !sh.can_write || !sh.org_id) return;  // a private table has nobody else to tell
  const cid = ed ? shvCell(ed.r, ed.c)?.id || null : null;
  SHV.presAt = Date.now();
  rawFetch('POST', `/api/sheets/${sh.id}/presence`, {cell_id: cid}).catch(() => {});
}

// ---- the view
function viewSheets() {
  // CI of 2.223.1: a draw between sheets.js and sheetfold.js (the module's files run one after the other) waits for the folders
  if (typeof shf_data !== 'function') { ld_later('sheets'); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const r = S.route;
  if (r.shl) return shvOverview(r.shl);
  if (r.shf) return shf_folderView(r.shf, x => shvCardHtml(x, null));  // 2.199.0 C (#2742): one folder (sheetfold.js)
  if (!r.sh) return shvOverview(null);
  if (SHV.errFor !== r.sh + ':' + S.v && (!SHV.sh || SHV.sh.id !== r.sh || (SHV.sh._v !== S.v && !SHV.ed))) shvLoad(r.sh);
  const sh = SHV.sh && SHV.sh.id === r.sh ? SHV.sh : null;
  if (!sh) return `<div class="shvwrap"><div class="shvtop"><a class="btn sm" href="#sheets">${ic('back', 's')}${tr('Tables')}</a></div><p class="muted lempty" role="status">${SHV.err && SHV.errFor === r.sh + ':' + S.v ? esc(SHV.err) : tr('Loading…')}</p></div>`;
  return shvSheetHtml(sh);
}
function shvOverview(lid) {
  const key = lid ? 'l:' + lid : 'all', d = SHV.idx[key];
  if (!d || d.v !== S.v) shvLoadIdx(key);
  const l = lid ? listById(lid) : null, ws = typeof wsCur === 'function' ? wsCur() : 'all';
  let items = d?.items || [];
  if (!lid && ws && ws !== 'all') items = items.filter(x => x.space === ws || x.shared_in);  // 2.124.0 C (#2113): shared with me: in every workspace
  const hooks = SHV_HOOKS.overview.length;
  const head = `<div class="shvtop">${lid ? `<a class="btn sm" href="#l/${lid}">${ic('back', 's')}${esc(l ? lname(l) : tr('Project'))}</a>` : ''}
    ${lid ? `<h2 class="shvh">${esc(tr('Tables of {0}', l ? lname(l) : ''))}</h2>` : ''}<span class="spacer"></span>
    ${hooks ? `<button type="button" class="iconbtn" data-shv="omenu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button>` : ''}
    ${!lid || (l && canEditList(lid)) ? `<button type="button" class="btn sm pri" data-shv="new">${ic('plus', 's')}${tr('New table')}</button>` : ''}</div>`;
  if (!d?.items) return `<div class="shvwrap shvov">${head}<p class="muted lempty" role="status">${d?.err ? esc(d.err) : tr('Loading…')}</p></div>`;
  if (!items.length && (lid || !shf_data().folders.length)) return `<div class="shvwrap shvov">${head}${symEmpty('sheet', lid ? tr('No tables attached yet.') : tr('No tables yet.'), tr('Lists and calculations; every cell can fetch figures from Kalmido: hours booked, budget, open tasks.'))}</div>`;
  const card = x => shvCardHtml(x, lid);
  // 2.199.0 C (#2742): the folders of a workspace as cards first, its tables in a folder only there (sheetfold.js)
  const fold = sp => !lid && sp !== 'shared' ? shf_cardsHtml(sp, null) : '';
  const groups = [...shvSpaces(), 'shared'].map(sp => [sp, items.filter(x => sp === 'shared' ? x.shared_in : x.space === sp && !x.shared_in), fold(sp)])
    .map(g => [g[0], lid ? g[1] : shf_topItems(g[1], g[0]), g[2]]).filter(g => g[1].length || g[2]);  // 2.124.0 C (#2113): + shared with me
  const many = groups.length > 1 || (!lid && shvSpaces().length > 1);
  return `<div class="shvwrap shvov">${head}${groups.map(([sp, xs, fs]) => `<section class="shvgrp" aria-label="${esc(shvSpaceName(sp))}">${many ? `<h3>${esc(shvSpaceName(sp))}</h3>` : ''}<ul class="shvcards">${fs}${xs.map(card).join('')}</ul></section>`).join('')}</div>`;
}
function shvCardHtml(x, lid) {
  return `<li class="shvcard" data-id="${x.id}"><a href="#sheets/${x.id}" class="shvcl">${ic('sheet')}<span class="shvct"><b>${esc(x.title || tr('Untitled table'))}</b>
      <span class="muted">${x.list_title && !lid ? esc(x.list_title) + ' · ' : ''}${x.updated_at ? esc(relTime(x.updated_at)) : ''}${x.updated_by_name ? ' · ' + esc(x.updated_by_name) : ''}${x.agent ? ' · ' + esc(tr('changed by an agent')) : ''}${x.sheets > 1 ? ' · ' + esc(trn('{0} sheet', '{0} sheets', x.sheets)) : ''}${x.shared && !x.shared_in ? ` · <span class="shs-mark">${ic('users', 's')}${tr('Shared')}</span>` : ''}</span></span></a>
    <button type="button" class="iconbtn" data-shv="cmenu" data-id="${x.id}" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More') + ': ' + (x.title || ''))}">${ic('dots')}</button></li>`;
}
// 2.152.3 B (#2619): the panel of tables (sidebar B on a computer): "All tables" (the overview) and "New table", then the
// tables of the shown workspace in the overview's order; tables attached to a project as one group per project, the shared
// ones as their own group (each folds per device, LS sbbFold 'sh:l<list id>' / 'sh:shared' / 'sh:s:<space>'). The open table
// in the accent; the index is the overview's (loaded once, again after a change, sbb_sync)
function shv_panelHtml() {
  const d = SHV.idx.all; if (!d || d.v === -1) shvLoadIdx('all');  // 2.152.3: only a missing or marked index (shvLive, own changes), no fetch per render
  const r = S.route, ws = typeof wsCur === 'function' ? wsCur() : 'all', cur = r.mod === 'sheets' && r.sh ? (SHV.sh?.id === r.sh && SHV.sh.book_id) || r.sh : null;
  const row = x => sbb_row('sheets/' + x.id, 'sheet', x.title || tr('Untitled table'), x.id === cur, `data-sbbsh="${x.id}"`);
  const grp = (g, label, xs) => `<div class="sgroup sbbp">${sbb_head(g, label, xs.length, sbb_folded(g) && xs.some(x => x.id === cur))}${sbb_folded(g) ? '' : xs.map(row).join('')}</div>`;
  const top = `<div class="sgroup sbbp">${sbb_row('sheets', 'all', tr('All tables'), r.mod === 'sheets' && !r.sh && !r.shl && !r.shf, 'data-sbbsh="all"')}</div>`;  // 2.224.0 B (#2816): "New table" only in the overview's head (a folder: its own button / menu)
  if (!d?.items) return top + `<p class="muted sbbtl">${esc(d?.err || tr('Loading…'))}</p>`;
  const items = ws && ws !== 'all' ? d.items.filter(x => x.space === ws || x.shared_in) : d.items;  // like the overview (2.124.0 C: shared ones in every workspace)
  // 2.199.0 C (#2742): one entry per workspace (a single workspace shown: only its entry) with its folders, the tables in no
  // folder and the projects as automatic groups (sheetfold.js); the shared ones stay a group of their own
  const sps = ws && ws !== 'all' && shvSpaces().includes(ws) ? [ws] : shvSpaces();
  return top + `<div class="sgroup sbbp sbbtree" role="group" aria-label="${esc(tr('Tables'))}">${typeof shf_panelTree === 'function' ? sbb_treeHtml(shf_panelTree(items, sps, cur)) : ''}</div>`
    + (items.some(x => x.shared_in) ? grp('sh:shared', tr('Shared with me'), items.filter(x => x.shared_in)) : '');
}
document.addEventListener('click', e => { if (e.target.closest?.('#side [data-act="sbb-shnew"]')) shvNew(null, S.route.mod === 'sheets' && S.route.shf || null); });  // 2.199.0 C (#2742): into the open folder
function shvSheetHtml(sh) {
  const cols = sh.columns, rows = shvVisRows(sh), all = sh.rows.length, w = sh.can_write;
  const filt = shvFilt(sh), nf = Object.keys(filt).length;
  const pres = shvPresHtml(sh);
  SHV.rset = shvRangeSet();
  const back = sh.list_id ? `<a class="btn sm" href="#sheets/l/${sh.list_id}" title="${esc(tr('Tables of {0}', sh.list_title || ''))}">${ic('back', 's')}<span class="shvbk">${esc(sh.list_title || tr('Project'))}</span></a>` : `<a class="btn sm" href="#sheets">${ic('back', 's')}<span class="shvbk">${tr('Tables')}</span></a>`;
  const top = `<div class="shvtop">${back}<h2 class="shvh"><button type="button" class="shvtitle" data-shv="rename" ${w ? '' : 'disabled'} title="${esc(w ? tr('Rename…') : '')}">${esc((sh.book_title ?? sh.title) || tr('Untitled table'))}</button></h2>
    ${w ? '' : `<span class="shvro">${ic('eye', 's')}${tr('Read only')}</span>`}<span class="spacer"></span>
    ${nf ? `<button type="button" class="btn sm" data-shv="unfilter" title="${esc(tr('Reset filters'))}">${ic('filter', 's')}${trn('{0} filter', '{0} filters', nf)}${ic('x', 's')}</button>` : ''}
    <button type="button" class="btn sm ${SHV.deps ? 'on' : ''}" data-shv="deps" aria-haspopup="menu" aria-pressed="${!!SHV.deps}">${ic('deps', 's')}<span class="shvbk">${tr('Dependencies')}</span></button>${typeof shz_btnsHtml === 'function' ? shz_btnsHtml(sh) : ''}
    <button type="button" class="iconbtn" data-shv="menu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  const c0 = SHV.cur && sh._col.has(SHV.cur.c) && sh._rowNo.has(SHV.cur.r) ? SHV.cur : null, cc = c0 && shvCell(c0.r, c0.c, sh);
  const bar = `<div class="shvbar"><span class="shvaddr" id="shv-addr" aria-live="polite">${c0 ? esc(cc?.name || shvAddr(c0.r, c0.c, sh)) : ''}</span><span class="shvfx" aria-hidden="true">fx</span>
    <input id="shv-in" value="${esc(cc?.raw || '')}" autocomplete="off" spellcheck="false" ${w && c0 ? '' : 'readonly'} aria-label="${esc(tr('Content of the cell'))}" placeholder="${esc(c0 ? (w ? tr('Value or =formula') : '') : tr('Choose a cell'))}"></div>`;
  const shz = typeof shz_plan === 'function' && shz_plan(sh);  // 2.98.0 C (#2181): sheetsize.js
  const colgroup = `<colgroup><col class="shvrhc">${cols.map(c => `<col data-c="${c.id}" style="width:${shvW(c) / 16}rem">`).join('')}${w ? '<col class="shvaddcc">' : ''}${shz ? shz_colsHtml(sh) : ''}</colgroup>`;  // 2.98.0 C (#2181): + the empty columns that fill the frame
  const head = `<thead><tr><th class="shvcorner" scope="col"><span class="sr">${tr('Row')}</span></th>${cols.map(c => shvTh(sh, c, filt)).join('')}${w ? `<th class="shvaddc"><button type="button" class="iconbtn" data-shv="coladd" title="${esc(tr('Add column'))}" aria-label="${esc(tr('Add column'))}">${ic('plus', 's')}</button></th>` : ''}${shz ? shz_headHtml(sh) : ''}</tr></thead>`;
  const body = `<tbody>${rows.map(r => shvTr(sh, r)).join('')}</tbody>${shz ? shz_bodyHtml(sh) : ''}`;
  const foot = `<div class="shvfoot">${w ? `<button type="button" class="btn sm" data-shv="rowadd">${ic('plus', 's')}${tr('Add row')}</button>` : ''}${nf ? `<span class="muted">${tr('{0} of {1} rows shown', rows.length, all)}</span>` : ''}</div>`;
  return `<div class="shvwrap shvsheet" data-k="shv-${sh.id}">${top}${pres}${shvRefsHtml(sh)}${typeof shc_html === 'function' ? shc_html(sh) : ''}${bar}
    <div class="shvbody"><div class="shvgridw"><div class="shzbox"${typeof shz_boxAttr === 'function' ? shz_boxAttr(sh) : ''}><div class="shvscroll" id="shv-scroll" tabindex="0" role="grid" aria-label="${esc(sh.title || tr('Table'))}" aria-rowcount="${all + 1}" aria-colcount="${cols.length + 1}" aria-multiselectable="true" ${c0 ? `aria-activedescendant="shv-c-${c0.r}-${c0.c}"` : ''}>
      <table class="shvgrid" role="presentation">${colgroup}${head}${body}</table><svg class="shvdeps" id="shv-deps" aria-hidden="true"></svg></div>${typeof shz_gripHtml === 'function' ? shz_gripHtml(sh) : ''}</div>${foot}${typeof shb_barHtml === 'function' ? shb_barHtml(sh) : ''}</div>
    <aside class="shvside" id="shv-side" aria-label="${esc(tr('Cell details'))}">${shvSideHtml(sh)}</aside></div></div>`;
}
function shvPresHtml(sh) {  // "Anna is editing B4" (others only)
  const others = shvOthers(sh);
  return others.length ? `<div class="shvpres" role="status">${ic('edit', 's')}<span>${others.map(p => esc(p.cell_id && sh._id.get(p.cell_id) ? tr('{0} is editing {1}', p.name, sh._id.get(p.cell_id).addr) : tr('{0} is editing', p.name))).join(' · ')}</span></div>` : '';
}
const shvW = c => Math.max(48, Math.min(640, +c.width || (c.kind === 'text' ? 160 : 112)));
function shvTh(sh, c, filt) {
  const sort = SHV.sorted?.sid === sh.id && SHV.sorted.c === c.id ? (SHV.sorted.dir > 0 ? ' ↑' : ' ↓') : '';
  return `<th class="shvch k-${c.kind}" scope="col" data-c="${c.id}" role="columnheader"><button type="button" class="shvchb" data-shv="col" data-c="${c.id}" aria-haspopup="menu" title="${esc(tr('Column menu: {0}', c.title || c.letter))}">
    <span class="shvlet">${esc(c.letter || '')}</span><span class="shvct">${esc(c.title || '')}${esc(sort)}</span>${filt[c.id] ? ic('filter', 's') : ''}</button>${sh.can_write && !isTouch() ? `<span class="shvrsz" data-rsz="${c.id}" aria-hidden="true"></span>` : ''}</th>`;
}
function shvRowColor(sh, r) {  // the first selection column that colours the whole row and has a coloured option in this row
  for (const c of sh.columns) {
    if (c.kind !== 'select' || c.color_mode !== 'row') continue;
    const o = shvOpt(c, shvCell(r.id, c.id, sh)); if (o && cssColor(o.color)) return cssColor(o.color);
  }
  return '';
}
function shvTr(sh, r) {
  const rc = shvRowColor(sh, r), n = sh._rowNo.get(r.id);
  return `<tr data-id="${r.id}" class="${rc ? 'shvrc' : ''}" ${rc ? `style="--shr:${rc}"` : ''} role="row" aria-rowindex="${n + 1}"><th class="shvrh" scope="row" data-r="${r.id}"><button type="button" data-shv="row" data-r="${r.id}" aria-haspopup="menu" title="${esc(tr('Row {0}', n))}">${n}</button>${(SHV_HOOKS.row || []).map(f => { try { return f(sh, r) || ''; } catch (er) { console.error(er); return ''; } }).join('')}</th>${sh.columns.map(c => shvTd(sh, r.id, c)).join('')}${sh.can_write ? '<td class="shvpad" aria-hidden="true"></td>' : ''}${typeof shz_rowTail === 'function' ? shz_rowTail(sh, r) : ''}</tr>`;
}
const shvOpt = (col, cell) => { if (!cell) return null; const os = col.options || [], k = cell.option ?? cell.raw; return os.find(o => o.id === k) || os.find(o => String(o.label || '').toLowerCase() === String(k ?? '').toLowerCase()) || null; };
function shvTd(sh, rid, col) {
  const c = shvCell(rid, col.id, sh), id = `shv-c-${rid}-${col.id}`;
  const sel = shvInRange(rid, col.id), cur = SHV.cur && SHV.cur.r === rid && SHV.cur.c === col.id;
  const pres = shvOthers(sh).find(p => c && p.cell_id === c.id);
  const cls = ['shvc', 'k-' + col.kind];
  let inner = '', style = '';
  if (c) {
    cls.push('o-' + (c.frozen ? 'frozen' : c.origin || 'own'));
    if (c.error) cls.push('err');
    if (c.agent) cls.push('ag');
    if (typeof c.value === 'number' || SHV_NUM.includes(col.kind)) cls.push('num');
    if (col.kind === 'select' && !c.error) {
      const o = shvOpt(col, c);
      if (o) { const cc = cssColor(o.color); inner = `<span class="shvopt${cc ? ' fill' : ''}" ${cc ? `style="--fc:${cc};--fct:${lrInk(cc)}"` : ''}>${esc(o.label)}</span>`; if (cc && col.color_mode !== 'row') { style = `--shc:${cc}`; cls.push('shvcc'); } }
    } else inner = shvShow(c);
  }
  if (typeof shk_td === 'function') { const x = shk_td(sh, col, c, rid, cls); if (x != null) inner = x; }  // 2.124.0 B (#2110): sheetkinds.js
  if (col.kind === 'select' && sh.can_write) inner += `<span class="shvdd" aria-hidden="true">${ic('down', 's')}</span>`;
  if (sel) cls.push('sel'); if (cur) cls.push('cur'); if (pres) cls.push('shvpc');
  const tip = c ? shvTip(c, pres) : '';
  return `<td id="${id}" class="${cls.join(' ')}" data-r="${rid}" data-c="${col.id}" role="gridcell" aria-selected="${!!sel}" ${style ? `style="${style}"` : ''} ${tip ? `title="${esc(tip)}"` : ''}>${inner}</td>`;
}
function shvShow(c) {  // what a cell reads (errors with their reason, "Source deleted" with the last value)
  if (c.error) {
    const t = c.error_text || tr(SHV_ERR[c.error] || N_('Error'));
    return `<span class="shverr">${ic('alert', 's')}<span>${esc(t)}</span></span>${c.error === 'deleted' && c.last_value != null && c.last_value !== '' ? `<span class="shvlast" title="${esc(tr('Last value'))}">${esc(c.last_value)}</span>` : ''}`;
  }
  return `${c.frozen ? ic('snow', 's') : ''}<span class="shvv">${esc(c.display ?? c.value ?? '')}</span>`;
}
function shvTip(c, pres) {  // hover text: name, formula (names, not ids), origin, agent, someone editing
  const out = [];
  if (c.name) out.push(c.name);
  if (String(c.raw || '').startsWith('=')) out.push(c.raw);
  if (c.error) out.push(c.error_text || tr(SHV_ERR[c.error] || N_('Error')));
  else if (c.origin === 'kalmido' || c.frozen) out.push(tr(SHV_ORIGIN[c.frozen ? 'frozen' : 'kalmido']));
  if (c.agent) out.push(tr('Changed by {0}', c.agent.name || tr('Agent')));
  if (pres) out.push(tr('{0} is editing', pres.name));
  return out.join('\n');
}
// ---- the panel: the chosen cell, the sources of the sheet, the agents' changes
function shvSideHtml(sh) {
  const cur = SHV.cur && sh._col.has(SHV.cur.c) && sh._rowNo.has(SHV.cur.r) ? SHV.cur : null;
  let cell = '';
  if (cur) {
    const c = shvCell(cur.r, cur.c, sh), col = sh._col.get(cur.c), addr = shvAddr(cur.r, cur.c, sh), w = sh.can_write;
    const isF = String(c?.raw || '').startsWith('=');
    const refBtn = id => { const x = sh._id.get(id); return x ? `<li><button type="button" class="linkbtn" data-shv="goto" data-id="${id}">${esc(x.name ? x.name + ' (' + x.addr + ')' : x.addr)}</button> <span class="muted">${esc(x.error ? tr(SHV_ERR[x.error] || N_('Error')) : x.display ?? '')}</span></li>` : ''; };
    const srcLi = s => `<li>${s.label ? `<a href="${s.type === 'k' ? '#client/' + +s.id : '#l/' + +s.id}" class="shvsrc">${ic(s.type === 'k' ? 'brief' : s.type === 'p' ? 'rocket' : 'list', 's')}${esc(s.label)}</a>` : `<span class="shverr">${ic('lock', 's')}${tr('No access')}</span>`}${s.field ? ` <code>${esc(s.field)}</code>` : ''}</li>`;
    const from = [...(c?.refs || []).map(refBtn), ...(c?.sources || []).map(srcLi)].filter(Boolean);
    const into = (c ? sh._into.get(c.id) || [] : []).map(refBtn).filter(Boolean);
    const origin = c ? (c.frozen ? 'frozen' : c.origin || 'own') : '';
    cell = `<section class="shvsec"><h4>${tr('Cell {0}', addr)}${col?.title ? ` <span class="muted">· ${esc(col.title)}</span>` : ''}</h4>
      <label class="shvrow2"><span>${tr('Name')}</span><input id="shv-name" value="${esc(c?.name || '')}" maxlength="60" autocomplete="off" spellcheck="false" placeholder="${esc(c ? tr('e.g. day_rate') : tr('Enter a value first'))}" ${w && c ? '' : 'disabled'}></label>
      ${c ? `<div class="shvkv"><span>${tr('Value')}</span><b class="shvval o-${origin}">${c.error ? shvShow(c) : esc(c.display ?? '')}</b></div>
      ${isF ? `<div class="shvkv"><span>${tr('Formula')}</span><code class="shvcode">${esc(c.raw)}</code></div>` : ''}
      <div class="shvkv"><span>${tr('Origin')}</span><span class="shvorg o-${origin}">${tr(SHV_ORIGIN[origin] || N_('Own value'))}</span></div>
      ${c.agent ? `<div class="shvkv shvagk"><span>${ic('bot', 's')}</span><span>${esc(tr('Changed by {0}', c.agent.name || tr('Agent')))}${w && c.agent.batch ? ` <button type="button" class="linkbtn" data-shv="bundo" data-b="${esc(c.agent.batch)}">${tr('Take back')}</button>` : ''}</span></div>` : ''}
      ${w && (isF || c.frozen) ? `<button type="button" class="btn sm" data-shv="freeze">${ic(c.frozen ? 'sync' : 'snow', 's')}${c.frozen ? tr('Live again') : tr('Freeze value')}</button>` : ''}
      <h5>${tr('Comes from')}</h5>${from.length ? `<ul class="shvrefs">${from.join('')}</ul>` : `<p class="muted mhint">${tr('Nothing – an own value.')}</p>`}
      <h5>${tr('Goes into')}</h5>${into.length ? `<ul class="shvrefs">${into.join('')}</ul>` : `<p class="muted mhint">${tr('No other cell uses it.')}</p>`}`
      : `<p class="muted mhint">${w ? tr('Empty. Type a value or a formula starting with =, e.g. {0}', '=B2*C2 · =SUMME(C2:C9) · =hier.zeit_gesamt') : tr('Empty.')}</p>`}</section>`;
  } else cell = `<section class="shvsec"><p class="muted mhint">${tr('Choose a cell to see where its value comes from.')}</p></section>`;
  const srcs = sh.sources || [];
  const src = srcs.length ? `<section class="shvsec"><h4>${tr('Kalmido sources')}</h4><ul class="shvrefs">${srcs.map(s => `<li>${s.denied ? `<span class="shverr">${ic('lock', 's')}${tr('No access')}</span>` : `<a href="${s.type === 'k' ? '#client/' + +s.id : '#l/' + +s.id}" class="shvsrc">${ic(s.type === 'k' ? 'brief' : s.type === 'p' ? 'rocket' : 'list', 's')}${esc(s.label || '')}</a>`}
      ${s.deleted ? ` <span class="shverr">${tr('Source deleted')}</span>` : s.denied ? '' : ` <span class="muted">${esc((s.fields || []).join(', '))}</span>`}</li>`).join('')}</ul></section>` : '';
  const bs = (sh.batches || []).slice(0, 12);
  const bat = bs.length ? `<section class="shvsec"><h4>${tr('Changes by agents')}</h4><ul class="shvrefs">${bs.map(b => `<li class="shvbat ${b.undone ? 'undone' : ''}">${ic('bot', 's')}<span>${esc(b.agent_name || tr('Agent'))} · ${trn('{0} change', '{0} changes', b.count || 0)}${b.created_at ? ' · ' + esc(relTime(b.created_at)) : ''}</span>
      ${b.undone ? `<span class="muted">${tr('Taken back')}</span>` : sh.can_write ? `<button type="button" class="btn sm" data-shv="bundo" data-b="${esc(b.batch)}">${tr('Take back')}</button>` : ''}</li>`).join('')}</ul></section>` : '';
  const ext = (SHV_HOOKS.side || []).map(f => { try { return f(sh) || ''; } catch (er) { console.error(er); return ''; } }).join('');  // 2.89.0 (#1916, D): carried over
  return cell + ext + src + bat;
}
// ---- rows shown (filters) and the selection
function shvFilt(sh = SHV.sh) { const f = SHV.filt[sh?.id] || {}; for (const k of Object.keys(f)) if (!sh?._col.has(+k)) delete f[k]; return f; }
function shvPass(sh, r, filt) {
  for (const [cid, f] of Object.entries(filt)) {
    const col = sh._col.get(+cid), c = shvCell(r.id, +cid, sh);
    if (col.kind === 'select') { if (f.opts?.length && !f.opts.includes(shvOpt(col, c)?.id || '')) return false; continue; }
    if (SHV_NUM.includes(col.kind) && (f.min != null || f.max != null)) {
      const v = typeof c?.value === 'number' ? c.value : NaN;
      if (Number.isNaN(v) || (f.min != null && v < f.min) || (f.max != null && v > f.max)) return false;
      continue;
    }
    if (f.q && !String(c?.display ?? c?.value ?? '').toLowerCase().includes(f.q.toLowerCase())) return false;
  }
  return true;
}
function shvVisRows(sh = SHV.sh) { const f = shvFilt(sh); return Object.keys(f).length ? sh.rows.filter(r => shvPass(sh, r, f)) : sh.rows; }
function shvGrid() {  // [rows ids], [col ids] in their shown order
  const sh = SHV.sh; return sh ? [shvVisRows(sh).map(r => r.id), sh.columns.map(c => c.id)] : [[], []];
}
function shvRect() {  // the selected rectangle {r0, r1, c0, c1} in shown indexes (null without a choice)
  if (!SHV.cur) return null;
  const [rs, cs] = shvGrid(), a = SHV.anc || SHV.cur;
  const r1 = rs.indexOf(SHV.cur.r), c1 = cs.indexOf(SHV.cur.c), r0 = rs.indexOf(a.r), c0 = cs.indexOf(a.c);
  if (r1 < 0 || c1 < 0) return null;
  return r0 < 0 || c0 < 0 ? {r0: r1, r1, c0: c1, c1} : {r0: Math.min(r0, r1), r1: Math.max(r0, r1), c0: Math.min(c0, c1), c1: Math.max(c0, c1)};
}
function shvRangeSet() {  // "row:col" of the cells in a range (empty without one; one cell is no range)
  if (!SHV.anc || !SHV.cur || (SHV.anc.r === SHV.cur.r && SHV.anc.c === SHV.cur.c)) return new Set();
  return new Set(shvRangeCells().flat().map(x => x.r + ':' + x.c));
}
const shvInRange = (r, c) => (SHV.rset || new Set()).has(r + ':' + c);
function shvRangeCells() {  // [[{r, c}]] rows of the rectangle (the active cell alone without a range)
  const q = shvRect(); if (!q) return [];
  const [rs, cs] = shvGrid(), out = [];
  for (let i = q.r0; i <= q.r1; i++) { const row = []; for (let j = q.c0; j <= q.c1; j++) row.push({r: rs[i], c: cs[j]}); out.push(row); }
  return out;
}
function shvSelect(r, c, extend) {  // the active cell (extend: the anchor stays, a range)
  if (!SHV.sh) return;
  if (!extend || !SHV.cur) SHV.anc = {r, c};
  SHV.cur = {r, c};
  shvPaintSel();
  const td = document.getElementById(`shv-c-${r}-${c}`);
  td?.scrollIntoView?.({block: 'nearest', inline: 'nearest'});
}
function shvPaintSel() {  // classes, the formula bar, the panel and the arrows of a new choice (no redraw of the grid)
  const sh = SHV.sh, sc = $('#shv-scroll'); if (!sh || !sc) return;
  sc.querySelectorAll('td.cur,td.sel').forEach(td => { td.classList.remove('cur', 'sel'); td.setAttribute('aria-selected', 'false'); });
  SHV.rset = shvRangeSet();
  for (const k of SHV.rset) { const [r, c] = k.split(':'); const td = document.getElementById(`shv-c-${r}-${c}`); if (td) { td.classList.add('sel'); td.setAttribute('aria-selected', 'true'); } }
  if (SHV.cur) { const td = document.getElementById(`shv-c-${SHV.cur.r}-${SHV.cur.c}`); td?.classList.add('cur'); td?.setAttribute('aria-selected', 'true'); sc.setAttribute('aria-activedescendant', `shv-c-${SHV.cur.r}-${SHV.cur.c}`); }
  shvBarSync(); shvSideSync(); shvDepsDraw();
}
function shvBarSync() {
  const sh = SHV.sh, inp = $('#shv-in'), ad = $('#shv-addr'); if (!sh || !inp) return;
  const cur = SHV.cur, c = cur && shvCell(cur.r, cur.c);
  if (ad) ad.textContent = cur ? (c?.name || shvAddr(cur.r, cur.c)) : '';
  if (document.activeElement !== inp && !(SHV.ed && SHV.ed.bar)) { inp.value = SHV.ed ? SHV.ed.val ?? '' : c?.raw || ''; inp.readOnly = !sh.can_write || !cur; inp.placeholder = cur ? (sh.can_write ? tr('Value or =formula') : '') : tr('Choose a cell'); }
}
function shvSideSync() { const s = $('#shv-side'); if (s && SHV.sh && !s.contains(document.activeElement)) s.innerHTML = shvSideHtml(SHV.sh); }
function shvAfter() { shvBarSync(); shvDepsDraw(); if (typeof shz_fill === 'function') shz_fill(); if (typeof shk_after === 'function') shk_after(); }  // 2.124.0 B (#2111): + the rows / columns kept in view  // 2.98.0 C (#2181): the empty cells that fill the frame
// after a write: the changed cells and the rows they colour are drawn in place (an open editor stays)
function shvPatchAll() {
  const sh = SHV.sh, tb = $('#shv-scroll tbody'); if (!sh || !tb) return;
  SHV.rset = shvRangeSet();
  const want = shvVisRows(sh).map(r => r.id).join(','), have = [...tb.children].map(t => t.dataset.id).join(',');
  const heads = [...($('#shv-scroll thead tr')?.querySelectorAll('th.shvch') || [])].map(t => t.dataset.c).join(',');
  if (want !== have || heads !== sh.columns.map(c => c.id).join(',')) { if (!SHV.ed) { viewSafeRender(); requestAnimationFrame(shvAfter); } else SHV.stale = true; return; }
  for (const r of shvVisRows(sh)) {
    const tr0 = tb.querySelector(`tr[data-id="${r.id}"]`); if (!tr0) continue;
    const rc = shvRowColor(sh, r); tr0.classList.toggle('shvrc', !!rc); if (rc) tr0.style.setProperty('--shr', rc); else tr0.style.removeProperty('--shr');
    for (const col of sh.columns) {
      if (SHV.ed && SHV.ed.r === r.id && SHV.ed.c === col.id && !SHV.ed.bar) continue;
      const td = document.getElementById(`shv-c-${r.id}-${col.id}`); if (!td) continue;
      const t = document.createElement('template'); t.innerHTML = shvTd(sh, r.id, col).trim();
      const n = t.content.firstElementChild; if (n && n.outerHTML !== td.outerHTML) td.replaceWith(n);
    }
  }
  const p = $('#shv-scroll')?.closest('.shvsheet')?.querySelector('.shvpres');
  if (p || shvOthers(sh).length) { const t = document.createElement('template'); t.innerHTML = shvPresHtml(sh); const np = t.content.firstElementChild; if (p && np) p.replaceWith(np); else if (p) p.remove(); else if (np) $('.shvsheet .shvtop')?.after(np); }
  shvBarSync(); shvSideSync(); shvDepsDraw();
  if (typeof shc_patch === 'function') shc_patch(sh);  // 2.124.0 A (#2115): the chart follows the cells (sheetchart.js)
}
// a write's answer {cells, rev}: the cells it changed and those that follow them
function shvMerge(sid, r, sent) {
  const sh = SHV.sh; if (!sh || sh.id !== sid || !r) return;
  const got = new Set();
  for (const c of r.cells || []) {
    got.add(c.row_id + ':' + c.col_id);
    const i = sh.cells.findIndex(x => x.row_id === c.row_id && x.col_id === c.col_id);
    const empty = (c.raw == null || c.raw === '') && !c.name && !c.frozen;
    if (empty) { if (i >= 0) sh.cells.splice(i, 1); } else if (i >= 0) sh.cells[i] = c; else sh.cells.push(c);
  }
  for (const s of sent || []) if (!got.has(s.row_id + ':' + s.col_id) && (s.raw == null || s.raw === '')) { const i = sh.cells.findIndex(x => x.row_id === s.row_id && x.col_id === s.col_id); if (i >= 0) sh.cells.splice(i, 1); }
  if (r.rev != null) sh.rev = r.rev;
  shvPrep(sh);
  shvPatchAll();
}

// ---- writing (each action one Undo step)
const shvRaw = (r, c) => shvCell(r, c)?.raw || '';
async function shvSend(sid, cells) { const r = await rawFetch('PUT', `/api/sheets/${sid}/cells`, {cells}); shvMerge(sid, r, cells); return r; }
async function shvPut(chg, label) {
  const sh = SHV.sh; if (!sh || !sh.can_write) return null;
  // 2.263.0 (#2977): a slash date in a date column goes as YYYY-MM-DD in the order of the region (en-US 10/23/2026)
  chg = chg.map(x => sh._col.get(x.col_id)?.kind === 'date' && /^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test((x.raw || '').trim()) ? {...x, raw: sgDay(x.raw) || x.raw} : x);
  chg = chg.filter(x => (x.raw ?? '') !== shvRaw(x.row_id, x.col_id));
  if (!chg.length) return null;
  const sid = sh.id, old = chg.map(x => ({row_id: x.row_id, col_id: x.col_id, raw: shvRaw(x.row_id, x.col_id)}));
  try { await shvSend(sid, chg); } catch (e) { toast(e.message); shvPatchAll(); return null; }
  const e = histAdd({label: label || tr('Table changed'), ids: [], snaps: [], lids: [],
    undo: async () => { await shvSend(sid, old.map(x => ({...x, verbatim: true}))); return {skipped: []}; }, redo: async () => { await shvSend(sid, chg.map(x => ({...x, verbatim: true}))); return {skipped: []}; }});  // 2.263.0 (#2976): stored texts go back as they are
  return e;
}
async function shvReload() { if (SHV.sh) await shvLoad(SHV.sh.id, true); }
// structural steps: one request, a reload, Undo by the counterpart request
async function shvStep(label, doFn, undoFn, msg, redoFn) {  // redoFn(res): the way forward again (restore), else doFn once more
  const sid = SHV.sh?.id; if (!sid) return;
  let res; try { res = await doFn(); } catch (e) { if (e.message !== 'auth') toast(e.message); return; }
  await shvLoad(sid, true);
  const e = histAdd({label, ids: [], snaps: [], lids: [],
    undo: async () => { await undoFn(res); if (SHV.sh?.id === sid) await shvLoad(sid, true); return {skipped: []}; },
    redo: async () => { if (redoFn) await redoFn(res); else res = await doFn(); if (SHV.sh?.id === sid) await shvLoad(sid, true); return {skipped: []}; }});
  if (msg) histToast(msg, e);
  return res;
}
async function shvNew(lid, fid) {  // 2.199.0 C (#2742): fid = into this folder (its workspace)
  const l = lid ? listById(lid) : null, sps = shvSpaces(), f = fid ? shf_folder(fid) : null;
  SHV.newSp = f ? f.space : l ? shvListSpace(l) : shvNewSpace();
  const sel = !l && !f && sps.length > 1 ? `<label class="shvnsp">${tr('Space')}<select data-shv-sp aria-label="${esc(tr('Space'))}">${sps.map(s => `<option value="${esc(s)}" ${s === SHV.newSp ? 'selected' : ''}>${esc(shvSpaceName(s))}</option>`).join('')}</select></label>` : '';
  const hint = l ? `<p class="muted mhint">${esc(tr('Attached to {0}: “here.” in a formula means this project.', lname(l)))}</p>` : '';
  const t = await askDialog({title: tr('New table'), html: sel + hint, input: {value: '', placeholder: tr('e.g. Quotation shoot, Equipment, Budget'), max: 120}, ok: tr('Create')});
  if (t == null) return;
  const sp = SHV.newSp; LS.set('shvSpace', sp);
  let r; try { r = await rawFetch('POST', '/api/sheets', {title: t.trim() || tr('Untitled table'), space: sp, ...(lid ? {list_id: lid} : {}), ...(f ? {folder_id: f.id} : {})}); } catch (e) { toast(e.message); return; }
  for (const d of Object.values(SHV.idx)) d.v = -1;
  go('sheets/' + r.id);
  const e = histAdd({label: tr('Created {0}', qn(r.title || '')), ids: [], snaps: [], lids: [],
    undo: async () => { await rawFetch('DELETE', '/api/sheets/' + r.id); shvAfterIdx(r.id, true); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', `/api/sheets/${r.id}/restore`); shvAfterIdx(r.id); return {skipped: []}; }});
  histToast(tr('Table {0} created', qn(r.title || '')), e);
}
function shvAfterIdx(id, gone) {
  for (const d of Object.values(SHV.idx)) d.v = -1;
  if (typeof sbb_sync === 'function') sbb_sync('sheets');  // 2.152.3 B (#2619): the panel loads the index again
  if (gone && S.route.mod === 'sheets' && (S.route.sh === id || SHV.sh?.book_id === id)) { SHV.sh = null; go(SHV.backTo || 'sheets'); return; }  // 2.124.0 E (#2116): + a further sheet of the table
  if (SHV.sh?.id === id) SHV.sh._v = -1;
  if (S.route.mod === 'sheets') renderView();
}
async function shvRename(id, cur) {
  const t = await askPrompt(tr('Rename table'), cur || '', {input: {max: 120}, ok: tr('Rename')});
  if (t == null || !t.trim() || t.trim() === cur) return;
  const set = async v => { await rawFetch('PATCH', '/api/sheets/' + id, {title: v}); shvAfterIdx(id); };
  try { await set(t.trim()); } catch (e) { toast(e.message); return; }
  const e = histAdd({label: tr('Renamed {0}', qn(t.trim())), ids: [], snaps: [], lids: [], undo: async () => { await set(cur); return {skipped: []}; }, redo: async () => { await set(t.trim()); return {skipped: []}; }});
  histToast(tr('Renamed'), e);
}
async function shvDelete(id, title, lid) {
  try { await rawFetch('DELETE', '/api/sheets/' + id); } catch (e) { toast(e.message); return; }
  SHV.backTo = lid ? 'sheets/l/' + lid : 'sheets';
  shvAfterIdx(id, true);
  const e = histAdd({label: tr('Deleted {0}', qn(title || '')), ids: [], snaps: [], lids: [],
    undo: async () => { await rawFetch('POST', `/api/sheets/${id}/restore`); shvAfterIdx(id); return {skipped: []}; },
    redo: async () => { await rawFetch('DELETE', '/api/sheets/' + id); shvAfterIdx(id, true); return {skipped: []}; }});
  histToast(tr('Table {0} deleted', qn(title || '')), e);
}
async function shvAttach(sh) {  // attach to a project / list of the same space (or detach)
  const sp = sh.space || (sh.org_id ? 'org:' + sh.org_id : 'private');
  const ls = (S.lists || []).filter(l => !l.is_inbox && !l.archived && !l.e2e && shvListSpace(l) === sp && canEditList(l.id));
  if (!ls.length) { toast(tr('No project of this space to attach it to')); return; }
  const items = [...(sh.list_id ? [{label: tr('Detach from {0}', sh.list_title || ''), icon: 'x', fn: () => shvSetList(sh, null)}, '-'] : []),
    ...ls.slice(0, 60).map(l => ({label: lname(l), icon: l.kind === 'project' ? 'rocket' : 'list', on: l.id === sh.list_id, fn: () => shvSetList(sh, l.id)}))];
  menu($('[data-shv="menu"]') || $('#view'), items, null, null, tr('Attach to a project'));
}
async function shvSetList(sh, lid) {
  const old = sh.list_id || null, id = sh.id; if (old === lid) return;
  const set = async v => { await rawFetch('PATCH', '/api/sheets/' + id, {list_id: v}); shvAfterIdx(id); if (SHV.sh?.id === id) await shvLoad(id, true); };
  try { await set(lid); } catch (e) { toast(e.message); return; }
  const e = histAdd({label: lid ? tr('Attached') : tr('Detached'), ids: [], snaps: [], lids: [], undo: async () => { await set(old); return {skipped: []}; }, redo: async () => { await set(lid); return {skipped: []}; }});
  histToast(lid ? tr('Attached to {0}', lname(listById(lid)) || '') : tr('Detached'), e);
}
// rows
async function shvRowAdd(afterId, above) {
  const sh = SHV.sh; if (!sh?.can_write) return;
  const sid = sh.id, before = new Set(sh.rows.map(r => r.id)), order0 = sh.rows.map(r => r.id);
  const doIt = async () => {
    await rawFetch('POST', `/api/sheets/${sid}/rows`, above ? {} : {after_row_id: afterId ?? sh.rows[sh.rows.length - 1]?.id ?? null, count: 1});
    const j = await rawFetch('GET', '/api/sheets/' + sid); const ids = (j.rows || []).map(r => r.id).filter(x => !before.has(x));
    if (above && ids.length) { const o = order0.slice(); o.splice(Math.max(0, o.indexOf(afterId)), 0, ...ids); await rawFetch('POST', `/api/sheets/${sid}/rows/order`, {ids: o}); }
    return ids;
  };
  const res = await shvStep(tr('Row added'), doIt, async ids => { for (const x of ids || []) await rawFetch('DELETE', `/api/sheets/${sid}/rows/${x}`); }, null,
    async ids => { for (const x of ids || []) await rawFetch('POST', `/api/sheets/${sid}/rows/${x}/restore`); });
  if (res?.length && SHV.sh) { SHV.cur = SHV.anc = {r: res[0], c: SHV.cur?.c ?? SHV.sh.columns[0]?.id}; shvRender(); }
  return res;
}
async function shvRowDel(rid) {
  const sid = SHV.sh?.id, n = SHV.sh?._rowNo.get(rid);
  await shvStep(tr('Row {0} deleted', n), () => rawFetch('DELETE', `/api/sheets/${sid}/rows/${rid}`), () => rawFetch('POST', `/api/sheets/${sid}/rows/${rid}/restore`), tr('Row {0} deleted', n));
}
function shvSortVal(col, c) {
  if (!c || c.error) return null;
  if (col.kind === 'select') { const o = shvOpt(col, c); return o ? (col.options || []).indexOf(o) : null; }
  if (typeof c.value === 'number') return c.value;
  const v = c.value ?? c.display; return v === '' || v == null ? null : String(v);
}
async function shvSort(cid, dir) {
  const sh = SHV.sh, col = sh?._col.get(cid); if (!col || !sh.can_write) return;
  const sid = sh.id, old = sh.rows.map(r => r.id);
  const ids = sh.rows.map(r => [r.id, shvSortVal(col, shvCell(r.id, cid))]).sort((a, b) => {
    if (a[1] == null || b[1] == null) return (a[1] == null) - (b[1] == null);  // empty ones stay at the end
    return (typeof a[1] === 'number' && typeof b[1] === 'number' ? a[1] - b[1] : String(a[1]).localeCompare(String(b[1]), LOCALE(), {numeric: true})) * dir;
  }).map(x => x[0]);
  if (ids.join() === old.join()) return;
  SHV.sorted = {sid, c: cid, dir};
  await shvStep(tr('Sorted by {0}', col.title || col.letter), () => rawFetch('POST', `/api/sheets/${sid}/rows/order`, {ids}), () => rawFetch('POST', `/api/sheets/${sid}/rows/order`, {ids: old}), tr('Sorted by {0}', col.title || col.letter));
}
// columns
async function shvColDel(cid) {
  const sh = SHV.sh, col = sh?._col.get(cid); if (!col) return;
  const sid = sh.id, used = (sh.cells || []).some(c => (c.refs || []).some(r => sh._id.get(r)?.col_id === cid) && c.col_id !== cid);
  if (used && !await askConfirm(tr('Delete column {0}?', col.title || col.letter), tr('Formulas use it and then show an error.'), {ok: tr('Delete'), danger: true})) return;
  await shvStep(tr('Column {0} deleted', col.title || col.letter), () => rawFetch('DELETE', `/api/sheets/${sid}/columns/${cid}`), () => rawFetch('POST', `/api/sheets/${sid}/columns/${cid}/restore`), tr('Column {0} deleted', col.title || col.letter));
}
async function shvColPatch(cid, body, label) {
  const sh = SHV.sh, col = sh?._col.get(cid); if (!col) return;
  const sid = sh.id, old = {}; for (const k of Object.keys(body)) old[k] = col[k] ?? null;
  if (JSON.stringify(old) === JSON.stringify(body)) return;
  await shvStep(label || tr('Column changed'), () => rawFetch('PATCH', `/api/sheets/${sid}/columns/${cid}`, body), () => rawFetch('PATCH', `/api/sheets/${sid}/columns/${cid}`, old));
}
function shvColModal(col, afterId) {  // a new column (col = null) or its settings: title, kind, options with colours, colour for cell / row, width
  const sh = SHV.sh; if (!sh?.can_write) return;
  const st = {kind: col?.kind || 'text', opts: JSON.parse(JSON.stringify(col?.options || [])), mode: col?.color_mode || 'cell', pal: null, width: shvW(col || {kind: 'text'})};
  if (!st.opts.length) st.opts = [{id: '', label: '', color: LCOLORS[1]}];
  const md = modal(`<h3>${col ? tr('Edit column') : tr('Add column')}</h3>
    <div class="row"><label for="shv-ct">${tr('Title')}</label><input id="shv-ct" value="${esc(col?.title || '')}" maxlength="60" placeholder="${esc(tr('e.g. Hours, Rate, Status'))}"></div>
    <div class="row"><label for="shv-ck">${tr('Kind')}</label><select id="shv-ck">${SHV_KINDS.map(([k, n]) => `<option value="${k}" ${st.kind === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div id="shv-cx"></div>
    <div class="row"><label for="shv-cw">${tr('Width')}</label><select id="shv-cw">${SHV_WIDTHS.map(([w, n]) => `<option value="${w}" ${Math.abs(st.width - w) < 20 ? 'selected' : ''}>${tr(n)}</option>`).join('')}${SHV_WIDTHS.some(([w]) => Math.abs(st.width - w) < 20) ? '' : `<option value="${st.width}" selected>${st.width}</option>`}</select></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="save">${col ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('shvcmd');
  const extra = () => {
    const x = $('#shv-cx', md);
    if (st.kind !== 'select') { x.innerHTML = st.kind === 'date' ? `<p class="muted mhint">${mdFirst() ? tr('Dates as MM/DD/YYYY or YYYY-MM-DD; a date plus a number gives a date that many days later.') : tr('Dates as DD.MM.YYYY or YYYY-MM-DD; a date plus a number gives a date that many days later.')}</p>` : ''; return; }
    x.innerHTML = `<h4>${tr('Options')}</h4><div class="optlist" role="list">${st.opts.map((o, i) => `<div class="optrow" data-i="${i}" role="listitem"><button type="button" class="swc" data-ocol="${i}" style="background:${cssColor(o.color) || 'var(--bg4)'}" title="${esc(tr('Color'))}" aria-label="${esc(tr('Color'))}" aria-expanded="${st.pal === i}"></button><input data-oname="${i}" value="${esc(o.label)}" maxlength="60" placeholder="${esc(tr('Option'))}"><button type="button" class="iconbtn" data-orm="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>${st.pal === i ? `<div class="colors lrpal" role="group" aria-label="${esc(tr('Color'))}">${LCOLORS.map((c, k) => `<button type="button" data-opal="${esc(c)}" style="background:${c || 'var(--bg4)'}" class="${(o.color || '') === c ? 'on' : ''}" aria-pressed="${(o.color || '') === c}" aria-label="${esc(c ? tr('Color {0}', k) : tr('No color'))}"></button>`).join('')}</div>` : ''}`).join('')}</div>
      <button type="button" class="btn sm" data-m="opt-add">${ic('plus', 's')}${tr('Add option')}</button>
      <fieldset class="shvmode"><legend>${tr('Colour of the option')}</legend><label class="chkl"><input type="radio" name="shv-cm" value="cell" ${st.mode !== 'row' ? 'checked' : ''}> ${tr('Colour for the cell')}</label><label class="chkl"><input type="radio" name="shv-cm" value="row" ${st.mode === 'row' ? 'checked' : ''}> ${tr('Colour for the whole row')}</label></fieldset>`;
  };
  extra();
  md.addEventListener('change', e => { if (e.target.id === 'shv-ck') { st.kind = e.target.value; extra(); } if (e.target.name === 'shv-cm') st.mode = e.target.value; });
  md.addEventListener('input', e => { const i = e.target.dataset.oname; if (i !== undefined) st.opts[+i].label = e.target.value; });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.ocol !== undefined) { st.pal = st.pal === +b.dataset.ocol ? null : +b.dataset.ocol; extra(); $(`[data-ocol="${b.dataset.ocol}"]`, md)?.focus(); return; }
    if (b.dataset.opal !== undefined) { const i = st.pal; st.opts[i].color = b.dataset.opal; st.pal = null; extra(); $(`[data-ocol="${i}"]`, md)?.focus(); return; }
    if (b.dataset.orm !== undefined) { st.opts.splice(+b.dataset.orm, 1); st.pal = null; extra(); return; }
    const a = b.dataset.m;
    if (a === 'opt-add') { st.opts.push({id: '', label: '', color: LCOLORS[(st.opts.length % (LCOLORS.length - 1)) + 1]}); extra(); $$('[data-oname]', md).pop()?.focus(); return; }
    if (a === 'close') { md.remove(); return; }
    if (a !== 'save') return;
    const title = $('#shv-ct', md).value.trim(), width = +$('#shv-cw', md).value || 120;
    const body = {title, kind: st.kind, width};
    if (st.kind === 'select') {  // new options get an id here (o + a number not used yet), the server checks the colours
      const used = new Set(st.opts.map(o => o.id).filter(Boolean)); let n = 1;
      body.options = st.opts.filter(o => o.label.trim()).map(o => { if (!o.id) { while (used.has('o' + n)) n++; o.id = 'o' + n; used.add(o.id); } return {id: o.id, label: o.label.trim(), color: cssColor(o.color) || ''}; });
      body.color_mode = st.mode;
    }
    md.remove();
    if (col) { await shvColPatch(col.id, body, tr('Column {0} changed', title || col.letter)); return; }
    const sid = sh.id, before = new Set(sh.columns.map(c => c.id));
    let cid = null;
    await shvStep(tr('Column {0} added', title), async () => {
      const r = await rawFetch('POST', `/api/sheets/${sid}/columns`, {title, kind: st.kind, ...(afterId ? {after_col_id: afterId} : {})});
      cid = r?.id || r?.column?.id || null;
      if (!cid) { const j = await rawFetch('GET', '/api/sheets/' + sid); cid = (j.columns || []).map(c => c.id).find(x => !before.has(x)) || null; }
      const rest = {...body}; delete rest.title; delete rest.kind;
      if (cid && Object.keys(rest).length) await rawFetch('PATCH', `/api/sheets/${sid}/columns/${cid}`, rest);
      return cid;
    }, async x => { if (x || cid) await rawFetch('DELETE', `/api/sheets/${sid}/columns/${x || cid}`); }, tr('Column {0} added', title),
    async x => { if (x || cid) await rawFetch('POST', `/api/sheets/${sid}/columns/${x || cid}/restore`); });
  });
  setTimeout(() => $('#shv-ct', md)?.focus(), 30);
}
async function shvFreeze(c) {
  const sh = SHV.sh, sid = sh.id, cid = c.id, to = !c.frozen;
  const set = async v => { const r = await rawFetch('POST', `/api/sheets/${sid}/cells/${cid}/freeze`, {frozen: v}); if (r?.cells) shvMerge(sid, r); else if (SHV.sh?.id === sid) await shvLoad(sid, true); };
  try { await set(to); } catch (e) { toast(e.message); return; }
  { const sd = $('#shv-side'); if (sd && SHV.sh?.id === sid) { sd.innerHTML = shvSideHtml(SHV.sh); sd.querySelector('[data-shv="freeze"]')?.focus({preventScroll: true}); } }  // 2.144.5 D (#2011): the button just tapped kept the panel from redrawing
  const e = histAdd({label: to ? tr('Value frozen') : tr('Live again'), ids: [], snaps: [], lids: [], undo: async () => { await set(!to); return {skipped: []}; }, redo: async () => { await set(to); return {skipped: []}; }});
  histToast(to ? tr('Value frozen: it stays as it is until you make it live again') : tr('Live again'), e);
}
async function shvName(c, name) {
  const sh = SHV.sh, sid = sh.id, cid = c.id, old = c.name || '';
  if (name === old) return;
  const set = async v => { const r = await rawFetch('POST', `/api/sheets/${sid}/cells/${cid}/name`, {name: v}); if (r?.cells) shvMerge(sid, r); else if (SHV.sh?.id === sid) await shvLoad(sid, true); };
  try { await set(name); } catch (e) { toast(e.message); const i = $('#shv-name'); if (i) { i.value = old; i.focus(); } return; }
  const e = histAdd({label: name ? tr('Name {0}', name) : tr('Name removed'), ids: [], snaps: [], lids: [], undo: async () => { await set(old); return {skipped: []}; }, redo: async () => { await set(name); return {skipped: []}; }});
  histToast(name ? tr('Cell named {0}: usable in formulas', name) : tr('Name removed'), e);
}
async function shvBatchUndo(batch) {
  const sh = SHV.sh; if (!sh) return;
  if (!await askConfirm(tr('Take back the changes of this agent call?'), tr('The cells get the values from before; a table the agent created goes to the trash.'), {ok: tr('Take back')})) return;
  try { await rawFetch('POST', `/api/sheets/${sh.id}/batches/${encodeURIComponent(batch)}/undo`); } catch (e) { toast(e.message); return; }
  toast(tr('Changes taken back'));
  for (const d of Object.values(SHV.idx)) d.v = -1;
  await shvLoad(sh.id, true);
}

// ---- editing a cell
function shvEditStart(typed, bar) {
  const sh = SHV.sh, cur = SHV.cur; if (!sh?.can_write || !cur) return;
  const col = sh._col.get(cur.c);
  if (col?.kind === 'select' && !bar && !(typed && typed.startsWith('='))) { shvOptMenu(cur.r, cur.c); return; }
  if (!bar && !(typed && typed.startsWith('=')) && typeof shk_edit === 'function' && shk_edit(cur, col, typed)) return;  // 2.124.0 B (#2110)
  const c = shvCell(cur.r, cur.c), val = typed != null ? typed : c?.raw || '';
  SHV.ed = {r: cur.r, c: cur.c, orig: c?.raw || '', val, typed: typed != null, bar: !!bar};
  shvPresence(SHV.ed);
  if (bar) return;
  const td = document.getElementById(`shv-c-${cur.r}-${cur.c}`); if (!td) { SHV.ed = null; return; }
  td.classList.add('editing');
  td.innerHTML = `<input class="shvin" id="shv-ed" value="${esc(val)}" autocomplete="off" spellcheck="false" aria-label="${esc(tr('Cell {0}', shvAddr(cur.r, cur.c)))}" ${col?.kind === 'date' ? `placeholder="${esc(tr('DD.MM.YYYY'))}"` : ''}>`;
  const inp = $('#shv-ed', td); inp.focus({preventScroll: true});
  { const tr0 = td.getBoundingClientRect(), vw = window.visualViewport?.width || innerWidth;  // 2.144.5 D (#2011): the field ends at the visible edge
    const room = vw - Math.max(tr0.left, 0) - 4; if (room < inp.offsetWidth) inp.style.width = Math.max(Math.min(tr0.width, room), 6 * 16) + 'px'; }
  const n = inp.value.length; inp.setSelectionRange(n, n);
  const b = $('#shv-in'); if (b) b.value = val;
  if (val.startsWith('=')) shvAcUpdate(inp);
}
async function shvEditEnd(save, move) {
  const ed = SHV.ed; if (!ed) return;
  const inp = ed.bar ? $('#shv-in') : $('#shv-ed'), v = inp ? inp.value : ed.val;
  SHV.ed = null; shvAcClose();
  if (SHV.presAt) shvPresence(null);
  const td = document.getElementById(`shv-c-${ed.r}-${ed.c}`);
  if (td && !ed.bar) { td.classList.remove('editing'); const t = document.createElement('template'); t.innerHTML = shvTd(SHV.sh, ed.r, SHV.sh._col.get(ed.c)).trim(); if (t.content.firstElementChild) td.replaceWith(t.content.firstElementChild); }
  if (move || !ed.bar) $('#shv-scroll')?.focus({preventScroll: true});
  if (save && v !== ed.orig) {
    const p = shvPut([{row_id: ed.r, col_id: ed.c, raw: v}], tr('Cell {0} changed', shvAddr(ed.r, ed.c)));
    if (move) shvMove(move);
    await p;
  } else { shvBarSync(); if (move) shvMove(move); }
  if (SHV.stale) shvRender();
}
function shvOptMenu(r, c, anchor) {  // a selection cell: its options as a menu (one tap)
  const sh = SHV.sh, col = sh?._col.get(c); if (!col || !sh.can_write) return;
  const cur = shvOpt(col, shvCell(r, c)), addr = shvAddr(r, c);
  const items = (col.options || []).map(o => ({label: o.label, swc: cssColor(o.color), on: cur?.id === o.id, fn: () => shvPut([{row_id: r, col_id: c, raw: o.id}], tr('Cell {0} changed', addr))}));
  items.push('-', {label: tr('(empty)'), icon: 'x', fn: () => shvPut([{row_id: r, col_id: c, raw: ''}], tr('Cell {0} emptied', addr))},
    {label: tr('Edit options…'), icon: 'edit', fn: () => shvColModal(col)});
  menu(anchor || document.getElementById(`shv-c-${r}-${c}`) || $('#shv-scroll'), items, null, null, col.title || col.letter);
}
function shvMove(d) {  // d: 'up' | 'down' | 'left' | 'right' | 'home' | 'end'; Enter on the last row adds one (a list grows)
  const [rs, cs] = shvGrid(); if (!rs.length || !cs.length) return;
  if (!SHV.cur) { shvSelect(rs[0], cs[0]); return; }
  let i = rs.indexOf(SHV.cur.r), j = cs.indexOf(SHV.cur.c);
  if (d === 'down' && i === rs.length - 1 && SHV.enterAdd && SHV.sh.can_write && !Object.keys(shvFilt()).length) { SHV.enterAdd = false; shvRowAdd(rs[i]); return; }
  SHV.enterAdd = false;
  if (d === 'up') i = Math.max(0, i - 1); else if (d === 'down') i = Math.min(rs.length - 1, i + 1);
  else if (d === 'left') j = Math.max(0, j - 1); else if (d === 'right') j = Math.min(cs.length - 1, j + 1);
  else if (d === 'home') j = 0; else if (d === 'end') j = cs.length - 1;
  shvSelect(rs[Math.max(0, i)], cs[Math.max(0, j)]);
}
function shvClearRange() {
  const cells = shvRangeCells().flat().filter(x => shvRaw(x.r, x.c) !== '');
  if (!cells.length) return;
  shvPut(cells.map(x => ({row_id: x.r, col_id: x.c, raw: ''})), cells.length > 1 ? trn('{0} cell emptied', '{0} cells emptied', cells.length) : tr('Cell {0} emptied', shvAddr(cells[0].r, cells[0].c)));
}
// copy / paste: text/plain = what the cells read (other apps), plus the raw contents (formulas) for this app
function shvCopy(e, cut) {
  const rows = shvRangeCells(); if (!rows.length) return;
  const sh = SHV.sh;
  const txt = rows.map(r => r.map(x => { const c = shvCell(x.r, x.c), col = sh._col.get(x.c); const s = String(col?.kind === 'select' ? shvOpt(col, c)?.label || '' : c?.error ? '' : c?.display ?? ''); return /[\t\n"]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }).join('\t')).join('\n');
  const raw = rows.map(r => r.map(x => { const c = shvCell(x.r, x.c), col = sh._col.get(x.c); return col?.kind === 'select' ? shvOpt(col, c)?.label || '' : c?.raw || ''; }));
  e.clipboardData.setData('text/plain', txt);
  try { e.clipboardData.setData('application/x-kalmido-sheet', JSON.stringify(raw)); } catch { /* not every browser */ }
  e.preventDefault();
  if (cut) shvClearRange();
  else toast(rows.length * rows[0].length > 1 ? trn('{0} cell copied', '{0} cells copied', rows.length * rows[0].length) : tr('Copied'));
}
async function shvPaste(e) {
  const sh = SHV.sh; if (!sh?.can_write || !SHV.cur) return;
  let data = null;
  try { const j = e.clipboardData.getData('application/x-kalmido-sheet'); if (j) data = JSON.parse(j); } catch { data = null; }
  if (!Array.isArray(data)) { const t = e.clipboardData.getData('text/plain'); if (!t) return; data = sgTsv(t); }
  e.preventDefault();
  const q = shvRect(), [rs, cs] = shvGrid();
  // a single value into a range fills the range, else the block starts at the range's top left cell
  const one = data.length === 1 && data[0].length === 1 && q && (q.r1 > q.r0 || q.c1 > q.c0);
  const i0 = q ? q.r0 : rs.indexOf(SHV.cur.r), j0 = q ? q.c0 : cs.indexOf(SHV.cur.c);
  const h = one ? q.r1 - q.r0 + 1 : data.length, w = one ? q.c1 - q.c0 + 1 : Math.max(...data.map(r => r.length));
  let rows = rs.slice(i0, i0 + h);
  const missing = h - rows.length, cut = Math.max(0, j0 + w - cs.length);
  if (missing > 0) {
    if (Object.keys(shvFilt()).length) { toast(tr('Paste fills only the rows shown; reset the filters for new rows')); }
    else {
      const before = new Set(sh.rows.map(r => r.id));
      try { await rawFetch('POST', `/api/sheets/${sh.id}/rows`, {after_row_id: sh.rows[sh.rows.length - 1]?.id ?? null, count: missing}); await shvLoad(sh.id, true); } catch (er) { toast(er.message); return; }
      rows = rows.concat(SHV.sh.rows.map(r => r.id).filter(x => !before.has(x)));
      SHV.pasteRows = SHV.sh.rows.map(r => r.id).filter(x => !before.has(x));
    }
  }
  const chg = [];
  rows.forEach((rid, a) => { for (let b = 0; b < w && j0 + b < cs.length; b++) { const v = one ? data[0][0] : data[a]?.[b] ?? ''; const col = SHV.sh._col.get(cs[j0 + b]); chg.push({row_id: rid, col_id: cs[j0 + b], raw: col?.kind === 'select' ? shvOptId(col, v) : v}); } });
  const added = SHV.pasteRows || []; SHV.pasteRows = null;
  const sid = sh.id, n = chg.length;
  const e1 = await shvPut(chg, trn('{0} cell pasted', '{0} cells pasted', n));
  if (e1 && added.length) {  // the rows the paste added go with its Undo
    const u = e1.undo, r = e1.redo;
    e1.undo = async () => { const x = await u(); for (const id of added) await rawFetch('DELETE', `/api/sheets/${sid}/rows/${id}`); if (SHV.sh?.id === sid) await shvLoad(sid, true); return x; };
    e1.redo = async () => { for (const id of added) await rawFetch('POST', `/api/sheets/${sid}/rows/${id}/restore`); if (SHV.sh?.id === sid) await shvLoad(sid, true); return r(); };
  }
  if (e1) histToast(trn('{0} cell pasted', '{0} cells pasted', n) + (cut ? ' · ' + trn('{0} column did not fit', '{0} columns did not fit', cut) : ''), e1);
  SHV.anc = {r: rows[0], c: cs[j0]}; SHV.cur = {r: rows[rows.length - 1], c: cs[Math.min(cs.length - 1, j0 + w - 1)]}; shvPaintSel();
}
const shvOptId = (col, v) => { const s = String(v || '').trim(); if (!s) return ''; const o = (col.options || []).find(x => x.id === s || String(x.label).toLowerCase() === s.toLowerCase()); return o ? o.id : s; };

// ---- suggestions after "=" (variables, names, columns, functions)
const SHV_TOK = /([A-Za-zÄÖÜäöüß_][\wÄÖÜäöüß.]*)$/u;
function shvAcUpdate(inp) {
  const sh = SHV.sh; if (!sh || !inp) return;
  const v = inp.value, pos = inp.selectionStart ?? v.length, before = v.slice(0, pos);
  if (!v.startsWith('=') || /"[^"]*$/.test(before.replace(/"[^"]*"/g, ''))) { shvAcClose(); return; }
  const m = SHV_TOK.exec(before), q = m ? m[1] : '';
  if (!m && !/[=+\-*/(;,&<>]\s*$/.test(before)) { shvAcClose(); return; }
  clearTimeout(SHV.acT);
  SHV.acT = setTimeout(async () => {
    let j; try { j = await rawFetch('GET', `/api/sheets/${sh.id}/vars?q=${encodeURIComponent(q)}`); } catch { return; }
    if (document.activeElement !== inp || inp.value.slice(0, inp.selectionStart ?? 0) !== before) return;
    const items = (j.vars || []).slice(0, 12);
    if (!items.length) { shvAcClose(); return; }
    SHV.ac = {items, i: 0, from: pos - q.length, to: pos, inp};
    shvAcDraw();
  }, 140);
}
function shvAcDraw() {
  const a = SHV.ac; if (!a) return;
  let box = $('#shv-ac');
  if (!box) { box = document.createElement('div'); box.id = 'shv-ac'; box.className = 'shvac'; box.setAttribute('role', 'listbox'); box.setAttribute('aria-label', tr('Suggestions')); document.body.appendChild(box); }
  box.innerHTML = a.items.map((x, i) => `<button type="button" role="option" class="${i === a.i ? 'on' : ''}" aria-selected="${i === a.i}" data-shvac="${i}" ${x.help ? `title="${esc(x.help)}"` : ''}><code>${esc(x.token)}</code><span class="shvacl">${esc(x.label || '')}</span>${x.value_display != null && x.value_display !== '' ? `<span class="shvacv">${esc(x.value_display)}</span>` : ''}</button>`).join('');
  // 2.144.5 D (#2011): beside the field, never over it: below when it fits above the keyboard, else on the roomier side, shortened to fit
  const r = a.inp.getBoundingClientRect(), vv = window.visualViewport;
  const vBot = vv ? vv.offsetTop + vv.height : innerHeight, vTop = vv ? vv.offsetTop : 0;
  box.style.maxHeight = ''; const h = Math.min(box.scrollHeight || 240, 16 * 16);
  const roomB = vBot - r.bottom - 8, roomA = r.top - vTop - 8, below = h <= roomB || roomB >= roomA;
  const mh = Math.max(4 * 16, Math.min(h, below ? roomB : roomA)); box.style.maxHeight = mh + 'px';
  box.style.left = Math.max(8, Math.min(r.left, innerWidth - box.offsetWidth - 8)) + 'px';
  box.style.top = (below ? r.bottom + 4 : Math.max(vTop + 4, r.top - 4 - box.offsetHeight)) + 'px';
  a.inp.setAttribute('aria-controls', 'shv-ac'); a.inp.setAttribute('aria-expanded', 'true');
  box.querySelector('.on')?.scrollIntoView?.({block: 'nearest'});
}
function shvAcClose() { SHV.ac?.inp?.setAttribute('aria-expanded', 'false'); SHV.ac = null; $('#shv-ac')?.remove(); }
function shvAcPick(i) {
  const a = SHV.ac; if (!a) return;
  const x = a.items[i], inp = a.inp, v = inp.value;
  let ins = x.token; if (x.kind === 'function' && v[a.to] !== '(') ins += '(';
  inp.value = v.slice(0, a.from) + ins + v.slice(a.to);
  const p = a.from + ins.length; inp.setSelectionRange(p, p); inp.focus();
  shvAcClose(); shvMirror(inp);
}
function shvMirror(inp) {  // the cell's editor and the formula bar show the same text
  if (SHV.ed) SHV.ed.val = inp.value;
  const o = inp.id === 'shv-ed' ? $('#shv-in') : $('#shv-ed'); if (o && o !== inp) o.value = inp.value;
}
// a click on a cell while writing a formula (after an operator, "(" or ";"): its address goes in (Shift: a range)
function shvRefInsert(r, c, extend) {
  const ed = SHV.ed, inp = ed && (ed.bar ? $('#shv-in') : $('#shv-ed')); if (!inp || !inp.value.startsWith('=')) return false;
  const pos = inp.selectionStart ?? inp.value.length, before = inp.value.slice(0, pos);
  const last = ed.ref && ed.ref.end === pos && before.endsWith(ed.ref.text);
  if (!last && !/[=+\-*/(;,&<>:]\s*$/.test(before)) return false;
  let text = shvAddr(r, c);
  const cell = shvCell(r, c); if (cell?.name && !extend) text = cell.name;
  let start = pos;
  if (last) { start = pos - ed.ref.text.length; if (extend && ed.ref.a) text = ed.ref.a + ':' + shvAddr(r, c); }
  inp.value = inp.value.slice(0, start) + text + inp.value.slice(pos);
  const p = start + text.length; inp.setSelectionRange(p, p);
  ed.ref = {end: p, text, a: last && extend ? ed.ref.a : shvAddr(r, c)};
  shvMirror(inp);
  return true;
}

// ---- arrows: from the sources to the chosen cell (and on to the cells that use it), or for the whole sheet
function shvDepsDraw() {
  const svg = $('#shv-deps'), sh = SHV.sh, sc = $('#shv-scroll'); if (!svg || !sh || !sc) return;
  const tb = sc.querySelector('table'); if (!tb) return;
  const pairs = [];
  if (SHV.deps === 2) { for (const c of sh.cells || []) for (const r of c.refs || []) pairs.push([r, c.id]); }
  else if (SHV.deps === 1 && SHV.cur) { const c = shvCell(SHV.cur.r, SHV.cur.c); if (c) { for (const r of c.refs || []) pairs.push([r, c.id]); for (const x of sh._into.get(c.id) || []) pairs.push([c.id, x]); } }
  if (!pairs.length) { svg.innerHTML = ''; svg.style.display = 'none'; return; }
  svg.style.display = ''; svg.style.left = tb.offsetLeft + 'px'; svg.style.top = tb.offsetTop + 'px';
  svg.setAttribute('width', tb.offsetWidth); svg.setAttribute('height', tb.offsetHeight);
  const pt = id => { const c = sh._id.get(id), td = c && document.getElementById(`shv-c-${c.row_id}-${c.col_id}`); return td ? [td.offsetLeft + td.offsetWidth / 2, td.offsetTop + td.offsetHeight / 2] : null; };
  const out = [];
  for (const [a, b] of pairs.slice(0, 400)) {
    const p = pt(a), q = pt(b); if (!p || !q || (p[0] === q[0] && p[1] === q[1])) continue;
    const dx = (q[0] - p[0]) / 2, dy = Math.abs(q[1] - p[1]) < 4 ? -18 : 0;
    out.push(`<path d="M${p[0]},${p[1]} C${p[0] + dx},${p[1] + dy} ${q[0] - dx},${q[1] + dy} ${q[0]},${q[1]}" marker-end="url(#shv-arr)"/><circle cx="${p[0]}" cy="${p[1]}" r="3"/>`);
  }
  svg.innerHTML = `<defs><marker id="shv-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker></defs>${out.join('')}`;
}

// ---- events (own listeners: data-shv; the grid owns its keys while it has the focus)
const shvTdOf = el => el?.closest?.('#shv-scroll td.shvc[data-r]');
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-shv],[data-shvac]');
  if (a?.dataset.shvac !== undefined) { e.preventDefault(); shvAcPick(+a.dataset.shvac); return; }
  if (!a || !$('#view')?.contains(a)) return;
  const k = a.dataset.shv, sh = SHV.sh;
  if (k === 'new') shvNew(S.route.shl || null);
  else if (k === 'omenu') menu(a, SHV_HOOKS.overview.flatMap(f => { try { return f(S.route.shl ? null : (typeof wsCur === 'function' ? wsCur() : 'all'), S.route.shl || null) || []; } catch (er) { console.error(er); return []; } }));
  else if (k === 'cmenu') {
    const id = +a.dataset.id, x = Object.values(SHV.idx).flatMap(d => d.items || []).find(y => y.id === id); if (!x) return;
    menu(a, [{label: tr('Open'), icon: 'sheet', fn: () => go('sheets/' + id)}, ...(x.shared_in && x.share_role !== 'write' ? [] : [{label: tr('Rename…'), icon: 'edit', fn: () => shvRename(id, x.title)}]),
      ...(x.shared_in ? [] : [...sh_smvItems(x),  // 2.96.0 B (#1941); 2.124.0 C (#2113): a shared table: no move / delete
      '-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => shvDelete(id, x.title, S.route.shl || null)}])]);
  }
  else if (!sh) return;
  const bk = sh?.book_id && sh.book_id !== sh.id ? {...sh, id: sh.book_id, title: sh.book_title} : sh;  // 2.124.0 E (#2116): title, list, delete = the whole table
  if (k === 'rename') shvRename(bk.id, bk.title);
  else if (k === 'menu') menu(a, [...(sh.can_write ? [{label: tr('Rename…'), icon: 'edit', fn: () => shvRename(bk.id, bk.title)},
      ...(sh.shared_in ? [] : [{label: sh.list_id ? tr('Attached to {0}…', sh.list_title || '') : tr('Attach to a project…'), icon: 'link', fn: () => shvAttach(bk)}])] : []),  // 2.124.0 C (#2113): not through a share
    ...(sh.list_id ? [{label: tr('Open {0}', sh.list_title || tr('Project')), icon: 'list', fn: () => go('l/' + sh.list_id)}] : []),
    ...SHV_HOOKS.menu.flatMap(f => { try { return f(sh) || []; } catch (er) { console.error(er); return []; } }),
    ...(sh.can_write && !sh.shared_in ? ['-', {label: (sh.tabs || []).length > 1 ? tr('Delete table') : tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => shvDelete(bk.id, bk.title, sh.list_id)}] : [])]);  // 2.124.0 C (#2113)
  else if (k === 'deps') menu(a, [{label: tr('No arrows'), on: !SHV.deps, fn: () => { SHV.deps = 0; shvRender(); }},
    {label: tr('Arrows for the chosen cell'), on: SHV.deps === 1, fn: () => { SHV.deps = 1; shvRender(); }},
    {label: tr('Arrows for the whole table'), on: SHV.deps === 2, fn: () => { SHV.deps = 2; shvRender(); }}]);
  else if (k === 'unfilter') { delete SHV.filt[sh.id]; shvRender(); }
  else if (k === 'rowadd') { SHV.enterAdd = false; shvRowAdd(null); }
  else if (k === 'coladd') shvColModal(null, sh.columns[sh.columns.length - 1]?.id || null);
  else if (k === 'col') shvColMenu(+a.dataset.c, a);
  else if (k === 'row') shvRowMenu(+a.dataset.r, a);
  else if (k === 'goto') { const c = sh._id.get(+a.dataset.id); if (c) { shvSelect(c.row_id, c.col_id); $('#shv-scroll')?.focus({preventScroll: true}); } }
  else if (k === 'freeze') { const c = SHV.cur && shvCell(SHV.cur.r, SHV.cur.c); if (c) shvFreeze(c); }
  else if (k === 'bundo') shvBatchUndo(a.dataset.b);
});
function shvColMenu(cid, a) {
  const sh = SHV.sh, col = sh._col.get(cid); if (!col) return;
  const w = sh.can_write, f = shvFilt(sh)[cid];
  menu(a, [...(w ? [{label: tr('Edit column…'), icon: 'edit', fn: () => shvColModal(col)}] : []),
    ...(w ? [{label: tr('Sort ascending'), icon: 'sort', fn: () => shvSort(cid, 1)}, {label: tr('Sort descending'), icon: 'sort', fn: () => shvSort(cid, -1)}] : []),
    {label: tr('Filter by this column…'), icon: 'filter', on: !!f, fn: () => shvFilterPop(cid, a)},
    ...(f ? [{label: tr('Remove filter'), icon: 'x', fn: () => { delete SHV.filt[sh.id][cid]; shvRender(); }}] : []),
    ...(w ? ['-', {label: tr('Insert column right'), icon: 'plus', fn: () => shvColModal(null, cid)},
      {label: tr('Delete column'), icon: 'trash', cls: 'flag-5', fn: () => shvColDel(cid)}] : []),
    ...(SHV_HOOKS.colmenu || []).flatMap(f => { try { return f(sh, col) || []; } catch (er) { console.error(er); return []; } })], null, null, col.title || col.letter);  // 2.124.0 B (#2111)
}
function shvRowMenu(rid, a) {
  const sh = SHV.sh; if (!sh?.can_write) { const c = sh?.columns[0]; if (c) shvSelect(rid, c.id); return; }
  menu(a, [{label: tr('Insert row above'), icon: 'up', fn: () => shvRowAdd(rid, true)}, {label: tr('Insert row below'), icon: 'down', fn: () => shvRowAdd(rid)},
    '-', {label: tr('Delete row'), icon: 'trash', cls: 'flag-5', fn: () => shvRowDel(rid)},
    ...(SHV_HOOKS.rowmenu || []).flatMap(f => { try { return f(sh, rid) || []; } catch (er) { console.error(er); return []; } })], null, null, tr('Row {0}', sh._rowNo.get(rid)));  // 2.124.0 B (#2111)
}
function shvFilterPop(cid, anchor) {  // a filter of the view: text contains / number from-to / options
  const sh = SHV.sh, col = sh._col.get(cid); if (!col) return;
  const all = SHV.filt[sh.id] || (SHV.filt[sh.id] = {}), f = all[cid] || {};
  const body = col.kind === 'select' ? `<div class="shvfo" role="group" aria-label="${esc(tr('Options'))}">${[...(col.options || []), {id: '', label: tr('(empty)')}].map(o => `<label class="chkl"><input type="checkbox" data-shvf-o="${esc(o.id)}" ${(f.opts || []).includes(o.id) ? 'checked' : ''}> ${o.color ? `<span class="shvopt fill" style="--fc:${cssColor(o.color)};--fct:${lrInk(cssColor(o.color))}">${esc(o.label)}</span>` : esc(o.label)}</label>`).join('')}</div>`
    : SHV_NUM.includes(col.kind) ? `<div class="shvfr"><label>${tr('From')}<input data-shvf="min" inputmode="decimal" value="${f.min ?? ''}"></label><label>${tr('To')}<input data-shvf="max" inputmode="decimal" value="${f.max ?? ''}"></label></div>`
    : `<label class="shvfq">${tr('Contains')}<input data-shvf="q" value="${esc(f.q || '')}" autocomplete="off"></label>`;
  const p = openPop(anchor, `<div class="shvfpop"><div class="mgh">${esc(tr('Filter: {0}', col.title || col.letter))}</div>${body}<div class="foot"><button type="button" class="btn sm" data-shvf-x>${tr('Remove filter')}</button><span class="spacer"></span><button type="button" class="btn sm pri" data-shvf-ok>${tr('Done')}</button></div></div>`);
  const num = s => parseNum(s);  // 2.263.0 (#2976)
  const apply = () => {
    const nf = {};
    if (col.kind === 'select') nf.opts = [...p.querySelectorAll('[data-shvf-o]:checked')].map(x => x.dataset.shvfO);
    else if (SHV_NUM.includes(col.kind)) { nf.min = num(p.querySelector('[data-shvf="min"]').value); nf.max = num(p.querySelector('[data-shvf="max"]').value); }
    else nf.q = p.querySelector('[data-shvf="q"]').value.trim();
    const on = nf.opts?.length || nf.min != null || nf.max != null || nf.q;
    if (on) all[cid] = nf; else delete all[cid];
    shvRender();
  };
  p.addEventListener('input', apply); p.addEventListener('change', apply);
  p.addEventListener('click', e => {
    if (e.target.closest('[data-shvf-x]')) { delete all[cid]; closePop(); shvRender(); }
    else if (e.target.closest('[data-shvf-ok]')) closePop();
  });
  p.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); closePop(); } });
  setTimeout(() => p.querySelector('input:not([type=checkbox])')?.focus(), 30);
}
document.addEventListener('change', e => { if (e.target.matches?.('[data-shv-sp]')) SHV.newSp = e.target.value; });
// pointer: select (mouse drag = range, Shift = range), a second tap / double click edits, a long press shows the name and formula
document.addEventListener('pointerdown', e => {
  const rz = e.target.closest?.('#shv-scroll .shvrsz[data-rsz]');
  if (rz && e.button === 0) { shvResize(e, +rz.dataset.rsz); return; }
  const td = shvTdOf(e.target); if (!td || !SHV.sh || e.button > 0) return;
  const r = +td.dataset.r, c = +td.dataset.c;
  if (SHV.ed && SHV.ed.r === r && SHV.ed.c === c && !SHV.ed.bar) return;  // a click inside the own editor
  if (SHV.ed && shvRefInsert(r, c, e.shiftKey)) { e.preventDefault(); return; }
  if (e.pointerType === 'touch') {
    clearTimeout(SHV.lp?.t);
    SHV.lp = {x: e.clientX, y: e.clientY, td, t: setTimeout(() => { SHV.lpDone = Date.now(); SHV.lp = null; shvTipPop(td); }, 500)};
    return;
  }
  if (SHV.ed) shvEditEnd(true);
  e.preventDefault();
  shvSelect(r, c, e.shiftKey);
  $('#shv-scroll')?.focus({preventScroll: true});
  SHV.drag = {r, c};
});
document.addEventListener('pointermove', e => {
  if (SHV.lp && Math.hypot(e.clientX - SHV.lp.x, e.clientY - SHV.lp.y) > 10) { clearTimeout(SHV.lp.t); SHV.lp = null; }
  if (!SHV.drag || e.pointerType === 'touch') return;
  const td = shvTdOf(document.elementFromPoint?.(e.clientX, e.clientY)); if (!td) return;
  const r = +td.dataset.r, c = +td.dataset.c;
  if (SHV.cur && (SHV.cur.r !== r || SHV.cur.c !== c)) { SHV.cur = {r, c}; shvPaintSel(); }
});
document.addEventListener('pointerup', () => { SHV.drag = null; if (SHV.lp) { clearTimeout(SHV.lp.t); SHV.lp = null; } });
document.addEventListener('pointercancel', () => { SHV.drag = null; if (SHV.lp) { clearTimeout(SHV.lp.t); SHV.lp = null; } });
document.addEventListener('contextmenu', e => { if (shvTdOf(e.target) && isTouch()) e.preventDefault(); });
document.addEventListener('click', e => {  // touch: tap = choose, a second tap on the chosen cell edits
  const td = shvTdOf(e.target); if (!td || !SHV.sh || !isTouch()) return;
  if (Date.now() - SHV.lpDone < 600) return;
  const r = +td.dataset.r, c = +td.dataset.c;
  if (SHV.ed && SHV.ed.r === r && SHV.ed.c === c) return;
  if (SHV.ed && shvRefInsert(r, c, false)) return;
  if (SHV.ed) shvEditEnd(true);
  if (SHV.cur && SHV.cur.r === r && SHV.cur.c === c) { SHV.sh.can_write ? shvEditStart(null) : shvTipPop(td); return; }
  shvSelect(r, c);
});
document.addEventListener('dblclick', e => {
  const td = shvTdOf(e.target); if (!td || !SHV.sh || isTouch() || SHV.ed) return;
  shvSelect(+td.dataset.r, +td.dataset.c); shvEditStart(null);
});
function shvTipPop(td) {  // the long press: name, formula, value, origin of a cell
  const sh = SHV.sh, r = +td.dataset.r, c = +td.dataset.c, cell = shvCell(r, c);
  shvSelect(r, c);
  const isF = String(cell?.raw || '').startsWith('=');
  openPop(td, `<div class="shvtip"><div class="mgh">${esc(cell?.name ? cell.name + ' · ' + shvAddr(r, c) : shvAddr(r, c))}</div>
    ${cell ? `${isF ? `<code class="shvcode">${esc(cell.raw)}</code>` : ''}<div>${cell.error ? shvShow(cell) : esc(cell.display ?? '')}</div><div class="muted">${tr(SHV_ORIGIN[cell.frozen ? 'frozen' : cell.origin || 'own'] || N_('Own value'))}</div>` : `<div class="muted">${tr('Empty.')}</div>`}
    ${sh.can_write ? `<div class="foot"><span class="spacer"></span><button type="button" class="btn sm pri" data-shvtip-edit>${tr('Edit')}</button></div>` : ''}</div>`)
    .addEventListener('click', ev => { if (ev.target.closest('[data-shvtip-edit]')) { closePop(); shvEditStart(null); } });
}
function shvResize(e, cid) {  // drag a column's right edge (desktop); one Undo step
  e.preventDefault(); e.stopPropagation();
  const colEl = $(`#shv-scroll col[data-c="${cid}"]`), col = SHV.sh?._col.get(cid); if (!colEl || !col) return;
  const x0 = e.clientX, w0 = shvW(col), rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  let w = w0;
  const mv = ev => { w = Math.max(48, Math.min(640, Math.round(w0 + (ev.clientX - x0) * 16 / rem))); colEl.style.width = w / 16 + 'rem'; shvDepsDraw(); };
  const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); if (Math.abs(w - w0) > 2) shvColPatch(cid, {width: w}, tr('Width of the column {0}', col.title || col.letter)); };
  addEventListener('pointermove', mv); addEventListener('pointerup', up);
}
// keys (window capture: the app's own shortcuts never see the keys of the grid or of a cell's editor)
window.addEventListener('keydown', e => {
  if (e.isComposing) return;
  const t = e.target;
  // the suggestions of an editor
  if (SHV.ac && t === SHV.ac.inp) {
    const n = SHV.ac.items.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); SHV.ac.i = (SHV.ac.i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n; shvAcDraw(); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); shvAcPick(SHV.ac.i); return; }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); shvAcClose(); return; }
  }
  if (t?.id === 'shv-ed' || t?.id === 'shv-in') {
    if (t.id === 'shv-in' && !SHV.ed) return;
    const arrows = SHV.ed && SHV.ed.typed && !SHV.ed.bar && !t.value.startsWith('=');  // typed over the cell: arrows move on, like a spreadsheet
    let mv = null;
    if (e.key === 'Enter' && !e.altKey) mv = e.shiftKey ? 'up' : 'down';
    else if (e.key === 'Tab') mv = e.shiftKey ? 'left' : 'right';
    else if (arrows && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) mv = e.key.slice(5).toLowerCase();
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); t.value = SHV.ed?.orig ?? ''; shvEditEnd(false, null).then(() => $('#shv-scroll')?.focus({preventScroll: true})); return; }
    if (mv) { e.preventDefault(); e.stopPropagation(); if (mv === 'down' && e.key === 'Enter') SHV.enterAdd = true; shvEditEnd(true, mv); return; }
    e.stopPropagation();
    return;
  }
  if (t?.id === 'shv-name' && e.key === 'Enter') { e.preventDefault(); t.blur(); return; }
  if (t?.id !== 'shv-scroll' || !SHV.sh) return;
  const k = e.key, mod = e.ctrlKey || e.metaKey;
  if (mod || e.altKey) { if (mod && (k === 'a' || k === 'A')) { e.preventDefault(); e.stopPropagation(); const [rs, cs] = shvGrid(); if (rs.length && cs.length) { SHV.anc = {r: rs[0], c: cs[0]}; SHV.cur = {r: rs[rs.length - 1], c: cs[cs.length - 1]}; shvPaintSel(); } } return; }
  const dirs = {ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Home: 'home', End: 'end'};
  if (dirs[k]) {
    e.preventDefault(); e.stopPropagation();
    if (e.shiftKey && SHV.cur) { const keep = SHV.anc || SHV.cur; shvMove(dirs[k]); SHV.anc = keep; shvPaintSel(); } else shvMove(dirs[k]);
    return;
  }
  if (k === 'Tab') { e.preventDefault(); e.stopPropagation(); shvMove(e.shiftKey ? 'left' : 'right'); return; }
  if (k === 'Enter' || k === 'F2') { e.preventDefault(); e.stopPropagation(); if (!SHV.cur) shvMove('down'); else if (SHV.sh.can_write) shvEditStart(null); return; }
  if (k === 'Escape') { if (SHV.anc && SHV.cur && (SHV.anc.r !== SHV.cur.r || SHV.anc.c !== SHV.cur.c)) { e.preventDefault(); e.stopPropagation(); SHV.anc = {...SHV.cur}; shvPaintSel(); } return; }
  if (k === 'Delete' || k === 'Backspace') { e.preventDefault(); e.stopPropagation(); if (SHV.sh.can_write) shvClearRange(); return; }
  if (k.length === 1 && SHV.cur && SHV.sh.can_write) { e.preventDefault(); e.stopPropagation(); shvEditStart(k); }
}, true);
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'shv-ed' || t.id === 'shv-in') {
    if (t.id === 'shv-in' && !SHV.ed && SHV.cur && SHV.sh?.can_write) { SHV.ed = {r: SHV.cur.r, c: SHV.cur.c, orig: shvRaw(SHV.cur.r, SHV.cur.c), val: t.value, bar: true}; shvPresence(SHV.ed); }
    shvMirror(t); shvAcUpdate(t);
  }
});
document.addEventListener('focusin', e => {
  if (e.target.id === 'shv-in' && SHV.cur && SHV.sh?.can_write && !SHV.ed) { const r = SHV.cur; SHV.ed = {r: r.r, c: r.c, orig: shvRaw(r.r, r.c), val: e.target.value, bar: true}; }
});
document.addEventListener('focusout', e => {
  const t = e.target;
  if ((t.id === 'shv-ed' || t.id === 'shv-in') && SHV.ed) {
    setTimeout(() => {  // a click on a suggestion or on a cell (formula reference) keeps the editor
      if (!SHV.ed || document.activeElement === t || document.activeElement?.closest?.('#shv-ac')) return;
      if ((t.id === 'shv-ed' && !SHV.ed.bar) || (t.id === 'shv-in' && SHV.ed.bar)) shvEditEnd(true);
    }, 120);
  }
  if (t.id === 'shv-name' && SHV.sh && SHV.cur) { const c = shvCell(SHV.cur.r, SHV.cur.c); if (c) shvName(c, t.value.trim()); }
});
document.addEventListener('mousedown', e => { if (e.target.closest?.('#shv-ac')) e.preventDefault(); }, true);
document.addEventListener('copy', e => { if (document.activeElement?.id === 'shv-scroll' && SHV.cur) shvCopy(e, false); });
document.addEventListener('cut', e => { if (document.activeElement?.id === 'shv-scroll' && SHV.cur && SHV.sh?.can_write) shvCopy(e, true); });
document.addEventListener('paste', e => { if (document.activeElement?.id === 'shv-scroll' && SHV.cur) shvPaste(e); });
window.addEventListener('resize', () => { if (S.route.mod === 'sheets' && SHV.deps) requestAnimationFrame(shvDepsDraw); });
// ---- 2.96.0 B (#1941): a table to the other workspace (private <-> organisation). The shared dialog (spacemove.js) shows the
// server's dry run (the list attachment that ends, carried-over rows that lose their link, formulas that show "No access");
// the move back is ONE undo step and brings the attachment and the links back where they fit again.
const sh_smvOrg = sp => sp && sp !== 'private' ? +sp.slice(4) : null;
function sh_smvItems(x) {
  if (!x || S.me?.kind === 'agent' || x.can_write === false || x.shared_in || !smv_can(sh_smvOrg(x.space))) return [];  // 2.124.0 C (#2113): + not through a share
  return [{label: tr('Move to another workspace…'), icon: 'brief', fn: () => sh_smvMove(x)}];
}
async function sh_smvMove(x) {
  const id = x.id, from = sh_smvOrg(x.space);
  const req = (to, extra) => rawFetch('POST', `/api/sheets/${id}/move-space`, {to: smv_ws(to), ...extra});
  const r = await smv_open({what: qn(x.title || tr('Untitled table')), from, check: to => req(to, {dry: 1}),
    run: async to => { try { return await req(to, {}); } catch (e) { toast(e.message); throw e; } }});
  if (!r || !r.ok) return;
  let mid = r.move_id;
  const after = () => { shvAfterIdx(id); if (SHV.sh?.id === id) shvLoad(id, true); };
  after();
  const e = histAdd({label: tr('Moved {0}', qn(x.title || '')), ids: [], snaps: [], lids: [], wsp: r.space,
    undo: async () => { const b = await req(from, {undo: mid}); mid = b.move_id; after(); return {skipped: []}; },
    redo: async () => { const b = await req(sh_smvOrg(r.space), {undo: mid}); mid = b.move_id; after(); return {skipped: []}; }});
  histToast(tr('Moved to {0}', shvSpaceName(r.space)), e);
}
SHV_HOOKS.menu.push(sh => sh_smvItems(sh));
(SHV_HOOKS.side = SHV_HOOKS.side || []).push(sh => {  // the last move between workspaces (both sides see it; 2.97.0 D #2051: names from the server)
  const m = sh.moved; if (!m) return '';
  return `<section class="shvsec shvsmv"><p class="muted">${ic('brief', 's')} ${esc(tr('Moved out of {0}', m.from_name || (m.from ? shvSpaceName(m.from) : tr('Organisation'))))} · ${esc(fmtWhen(m.at))}${m.by_name ? ' · ' + esc(m.by_name) : ''}</p></section>`;
});
if (typeof sbb_sync === 'function') sbb_sync('sheets');  // 2.152.3 B: loaded later than the panel was drawn (lazyload.js): its panel now
