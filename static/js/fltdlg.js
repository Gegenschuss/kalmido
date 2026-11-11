// @ts-check
/* Kalmido web client: 2.521.0 (#4479, #4478) the dialog of a saved filter, loaded on demand (lazyload.js module fltdlg; its stand-in
   filterModal loads it, LD_CALL). The filter is a list of condition rows "what / comparison / value / x" with one
   AND / OR for all of them (no groups); it starts empty with "+ Condition". What: project, folder (with its subfolders), date,
   priority, ticket type, tag, assignee, column (only the chosen projects' columns, else all), sprint, milestone, delivery
   state, text and the custom fields (one entry per name and type: it holds in every project with such a field). A value list
   is the app's menu with its search field (tch_menuSearch) and a check per chosen value; "is none of" always holds on top,
   also with OR (filterMatch, views.js). An old filter opens converted (flt_conds) and hits the same tasks; saving stores
   {op, conds}. A live count shows how many open tasks match.
   2.846.0 (#5520): the dialog part of the shared core's filter (fltkern.js holds the rules): kflt_rows draws and runs the
   condition rows of any catalog, kflt_dialog is the whole dialog of a saved filter (name, AND / OR, rows, live count, save /
   delete). The lists (filterModal, the catalog flt_cat below) and the newsletter segments (newsletter.js) use only these;
   a new area passes its own catalog (docs/dev/kern.md "Filter").
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- the core's dialog (#5520) ------------------------------------------------------------------------------------------
// The catalog of fltkern.js plus what the rows show (all optional but what / ops / vals):
//   what(c, cs, ctx) -> [[key, label]]   the "what" entries (labels translated here)    extra(c, cs, ctx) -> [[key, label]] an
//   ops(c) -> [op]                        the comparisons of a row                       optgroup "Custom fields" (shown as is)
//   vals(c, cs) -> [[value, label]]       the values of a value list                     key(c) -> the row's key (default c.f)
//   fresh(key, cs, prev) -> condition     a row switched to key (default {f: key, op: the first of ops, v: []})
//   add(cs) -> key                        the "what" of "+ Condition" (default the first)  prep(cs) -> ctx  once per drawing
//   unit(c) -> text after a number        keep(c) -> false = an opened filter leaves the condition out
//   2.857.0 (#5518): input(c) -> 'date' = a date field instead of a number (op from / to), ph(c) -> the text field's placeholder;
//   count (kflt_dialog) may answer with a Promise (a count on the server): the newest answer is shown
const KFLT_OPN = {in: N_('is one of'), nin: N_('is none of'), empty: N_('is empty'), has: N_('contains'), nhas: N_('does not contain'),
  gt: N_('greater than'), lt: N_('less than'), eq: N_('equals'), set: N_('has a value'),
  is: N_('is'), isnot: N_('is not'),  // 2.625.0 (#4486): is / is not = the comparisons of a newsletter segment's rows (a value list)
  from: N_('from'), to: N_('to')};  // 2.857.0 (#5518): a date / number from / to (the documents' filter)
const kflt_isList = c => !['has', 'nhas', 'gt', 'lt', 'eq', 'set', 'empty', 'from', 'to'].includes(c.op);  // 2.857.0 (#5518): + from / to
const kflt_sum = (c, cs, /** @type {any} */ cat) => { const on = new Set((c.v || []).map(String)); const n = cat.vals(c, cs).filter(([v]) => on.has(String(v))).map(x => x[1]); return n.length ? n.join(', ') : ''; };
function kflt_fresh(key, cs, prev, /** @type {any} */ cat) {
  if (cat.fresh) return cat.fresh(key, cs, prev);
  const c = {f: key, op: 'in', v: /** @type {any} */ ([])}; c.op = cat.ops(c)[0]; if (!kflt_isList(c)) c.v = ''; return c;
}
function kflt_rowHtml(c, i, cs, /** @type {any} */ cat, ctx = null) {
  const key = cat.key ? cat.key(c) : c.f, std = cat.what(c, cs, ctx), cfo = cat.extra ? cat.extra(c, cs, ctx) : [];
  const opt = (/** @type {any} */ [k, n], t = true) => `<option value="${esc(k)}" ${k === key ? 'selected' : ''}>${esc(t ? tr(n) : n)}</option>`;
  const what = `<select class="fc-f" data-i="${i}" aria-label="${esc(tr('Condition'))}">${std.map(x => opt(x)).join('')}${cfo.length ? `<optgroup label="${esc(tr('Custom fields'))}">${cfo.map(x => opt(x, false)).join('')}</optgroup>` : ''}</select>`;
  const ops = `<select class="fc-op" data-i="${i}" aria-label="${esc(tr('Comparison'))}">${cat.ops(c).map(o => `<option value="${o}" ${o === c.op ? 'selected' : ''}>${esc(tr(KFLT_OPN[o]))}</option>`).join('')}</select>`;
  const unit = cat.unit ? cat.unit(c) : null;
  const val = c.op === 'empty' || c.op === 'set' ? '<span class="fc-vn"></span>'
    : c.op === 'has' || c.op === 'nhas' ? `<input class="fc-t" data-i="${i}" value="${esc(c.v || '')}" placeholder="${esc(cat.ph ? cat.ph(c) : tr('Title or notes contain …'))}" aria-label="${esc(tr('Value'))}" autocomplete="off">`
    : !kflt_isList(c) ? `<span class="fc-num">${/*html-ok*/ cat.input?.(c) === 'date' ? dateIn('fc-d' + i, c.v ?? '', {label: tr('Value'), attrs: 'class="fc-n" data-i="' + i + '"'}) : `<input class="fc-n" data-i="${i}" inputmode="decimal" value="${esc(c.v ?? '')}" aria-label="${esc(tr('Value'))}">`}${unit ? `<span class="muted">${esc(unit)}</span>` : ''}</span>`
    : (s => `<button type="button" class="btn sm fc-v${s ? '' : ' fc-v0'}" data-i="${i}" aria-haspopup="menu" aria-label="${esc(tr('Value'))}: ${esc(s || tr('Select'))}"><span class="fc-vs">${esc(s || tr('Select') + '…')}</span>${ic('chev', 's')}</button>`)(kflt_sum(c, cs, cat));
  return `<div class="fcond" data-i="${i}">${what}${ops}${val}<button type="button" class="iconbtn fc-x" data-i="${i}" aria-label="${esc(tr('Remove condition'))}" title="${esc(tr('Remove condition'))}">${ic('x', 's')}</button></div>`;
}
// the value menu: the app's menu (with its search from 8 entries), a click switches one value and keeps the menu open
function kflt_valMenu(btn, c, cs, /** @type {any} */ cat, done) {
  const opts = cat.vals(c, cs), on = new Set((c.v || []).map(String));
  const p = menu(btn, opts.map(([v, n]) => ({label: n, on: on.has(String(v)), fn: () => {}})), null, null, tr(cat.what(c, cs, cat.prep ? cat.prep(cs) : null).find(x => x[0] === c.f)?.[1] || 'Value'));
  if (opts.length >= 8) tch_menuSearch(p);
  const items = () => $$('[data-i]', p).filter(b => !b.closest('[hidden]') && !b.hidden);
  for (const b of $$('[data-i]', p)) { b.setAttribute('role', 'menuitemcheckbox'); b.setAttribute('aria-checked', String(b.classList.contains('on'))); }
  p.onclick = e => {
    const b = e.target.closest('[data-i]'); if (!b) return;
    const x = opts[+b.dataset.i][0], was = (c.v || []).some(y => String(y) === String(x));
    c.v = was ? c.v.filter(y => String(y) !== String(x)) : [...(c.v || []), x];
    b.classList.toggle('on', !was); b.setAttribute('aria-checked', String(!was));
    if (was) b.querySelector('.mchk')?.remove(); else b.insertAdjacentHTML('beforeend', `<span class="mchk" aria-hidden="true">${ic('check', 's')}</span>`);
    done();
  };
  p.addEventListener('keydown', e => {  // the menu's own keys know only menuitem rows; the search field has its own (Enter, down)
    if (/** @type {HTMLElement} */ (e.target).id === 'mq-q') return;
    const list = items(), i = list.indexOf(/** @type {HTMLElement} */ (document.activeElement));
    const to = {ArrowDown: i + 1, ArrowUp: i < 0 ? list.length - 1 : i - 1, Home: 0, End: list.length - 1}[e.key];
    if (to != null && list.length) { e.preventDefault(); e.stopPropagation(); list[(to + list.length) % list.length].focus(); }
  });
  setTimeout(() => { if (p.contains(document.activeElement) || isTouch()) return; ($('#mq-q', p) || items()[0])?.focus({preventScroll: true}); }, 0);
  return p;
}
// the condition rows of cs (changed in place) in host: drawing, switching what / comparison, values, removing.
// o.changed() after every change (a live count), o.addBtn gets the focus when the last row goes. -> {draw, add}
function kflt_rows(/** @type {any} */ host, /** @type {any[]} */ cs, /** @type {any} */ cat, /** @type {any} */ o = {}) {
  const draw = (focus = null) => {
    const ctx = cat.prep ? cat.prep(cs) : null;
    host.innerHTML = cs.map((c, i) => kflt_rowHtml(c, i, cs, cat, ctx)).join('');
    if (focus) $(`.fcond[data-i="${focus[0]}"] ${focus[1]}`, host)?.focus();
    o.changed?.();
  };
  host.addEventListener('change', e => {
    const el = /** @type {HTMLSelectElement} */ (e.target), i = +(el.dataset.i ?? -1), c = cs[i]; if (!c) return;
    if (el.classList.contains('fc-f')) { cs[i] = kflt_fresh(el.value, cs, c, cat); draw([i, '.fc-f']); return; }
    if (el.classList.contains('fc-op') && cat.ops(c).includes(el.value)) {
      const was = kflt_isList(c); c.op = el.value;
      if (kflt_isList(c) !== was) c.v = kflt_isList(c) ? [] : '';
      draw([i, '.fc-op']);
    }
  });
  host.addEventListener('input', e => {
    const el = /** @type {HTMLInputElement} */ (e.target), c = cs[+(el.dataset.i ?? -1)]; if (!c) return;
    if (el.classList.contains('fc-t')) { c.v = el.value; o.changed?.(); }
    if (el.classList.contains('fc-n')) { const v = el.value.trim(); c.v = v === '' || el.dataset.dp === 'date' ? v : numIn(v); o.changed?.(); }  // 2.857.0 (#5518): a date stays its text; 2.898 (#5518): the app's own date picker (ux1_ui: no native date inputs)
  });
  host.addEventListener('click', e => {
    const b = /** @type {HTMLElement} */ (e.target).closest('button'); if (!b || !host.contains(b)) return;
    if (b.classList.contains('fc-v')) {
      const i = +b.dataset.i, c = cs[i];
      kflt_valMenu(b, c, cs, cat, () => { const s = kflt_sum(c, cs, cat); const x = $(`.fcond[data-i="${i}"] .fc-v`, host); if (x) { $('.fc-vs', x).textContent = s || tr('Select') + '…'; x.classList.toggle('fc-v0', !s); x.setAttribute('aria-label', `${tr('Value')}: ${s || tr('Select')}`); } o.changed?.(); });
      return;
    }
    if (b.classList.contains('fc-x')) { cs.splice(+b.dataset.i, 1); draw(cs.length ? [Math.max(0, +b.dataset.i - 1), '.fc-x'] : null); if (!cs.length) o.addBtn?.focus(); }
  });
  const add = () => { cs.push(kflt_fresh(cat.add ? cat.add(cs) : cat.what(null, cs, cat.prep ? cat.prep(cs) : null)[0][0], cs, null, cat)); draw([cs.length - 1, '.fc-f']); };
  draw();
  return {draw, add};
}
// the dialog of a saved filter: o = {cat, rules, title, name, placeholder, more: html under the name, moreRules: md -> {extra keys},
// count: rules -> text (the live count), save: async (name, rules, md), del: async md (omitted = no Delete)} -> the dialog
function kflt_dialog(/** @type {any} */ o) {
  const cat = o.cat, r0 = o.rules && typeof o.rules === 'object' ? o.rules : {}, r = {op: r0.op === 'or' ? 'or' : 'and'};
  // an old filter opens converted; a condition the catalog no longer knows (cat.keep) stays out
  const cs = JSON.parse(JSON.stringify(kflt_conds(r0, cat))).filter(c => c && (!cat.keep || cat.keep(c)));
  const md0 = modal(`<h3>${esc(o.title)}</h3>
    <div class="row"><label for="f-name">${tr('Name')}</label><input id="f-name" value="${esc(o.name || '')}" placeholder="${esc(o.placeholder || tr('e.g. Important this week'))}"></div>${/*html-ok*/ o.more || ''}
    <div class="row"><label>${tr('Match')}</label><div class="seg" id="f-op"><button data-op="and" class="${r.op !== 'or' ? 'on' : ''}">${tr('AND: all conditions')}</button><button data-op="or" class="${r.op === 'or' ? 'on' : ''}">${tr('OR: any one')}</button></div></div>
    <div id="f-conds" class="fconds" role="group" aria-label="${esc(tr('Conditions'))}"></div>
    <div><button type="button" class="btn sm" data-m="cond-add">${ic('plus', 's')} ${tr('Condition')}</button></div>
    <div class="muted" id="f-count" role="status" style="font-size:var(--fs-m);margin-top:.875rem"></div>
    <div class="foot">${o.del ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  const md = /** @type {any} */ (md0);  // $() / $$() are typed for a Document root
  md.classList.add('fltdlg');
  const rules = () => ({op: r.op, conds: cs.filter(c => kflt_cond(c, cat)).map(c => ({...c})), ...(o.moreRules ? o.moreRules(md) : {})});
  const count = () => {
    if (!o.count) return;
    const hint = r.op === 'or' && cs.some(c => (cat.hard || KFLT_HARD).includes(c.op) && kflt_cond(c, cat)) ? ' ' + tr('“is none of” always applies on top, also with OR.') : '';
    const t = o.count(rules()), n = ++seq;
    if (t && typeof t.then === 'function') t.then(x => { if (n === seq && x != null) $('#f-count', md).textContent = x + hint; }, () => {});  // 2.857.0 (#5518): a count on the server
    else $('#f-count', md).textContent = t + hint;
  };
  let seq = 0;
  const rows = kflt_rows($('#f-conds', md), cs, cat, {changed: count, addBtn: $('[data-m="cond-add"]', md)});
  md.addEventListener('click', async e => {
    const b = /** @type {HTMLElement} */ (e.target).closest('button'); if (!b || b.closest('#f-conds')) return;
    if (b.dataset.op) { r.op = b.dataset.op === 'or' ? 'or' : 'and'; $$('#f-op button', md).forEach(x => x.classList.toggle('on', x === b)); count(); return; }
    const a = b.dataset.m;
    if (a === 'cond-add') { rows.add(); return; }
    if (a === 'close') md.remove();
    if (a === 'save') { const name = $('#f-name', md).value.trim(); if (!name) return $('#f-name', md).focus(); await o.save(name, rules(), md); }
    if (a === 'del') await o.del(md);
  });
  if (!o.name) setTimeout(() => $('#f-name', md)?.focus(), 50);
  return md;
}

// ---- the lists' catalog: tasks (#4479) ------------------------------------------------------------------------------------

const FLT_WHAT = [['list', N_('Project')], ['folder', N_('Folder')], ['date', N_('Date')], ['prio', N_('Priority')], ['type', N_('Ticket type')], ['tag', N_('Tag')],
  ['who', N_('Assignee')], ['sec', N_('Column')], ['sprint', N_('Sprint')], ['ms', N_('Milestone')], ['dlv', N_('Delivery state')], ['text', N_('Text')]];
FLT_WHAT.splice(FLT_WHAT.length - 1, 0, ['kind', N_('Column meaning')]);  // 2.577.0 (#3354): the state (section_kind); only offered while a column has a meaning
const FLT_OPN = KFLT_OPN;  // 2.846.0 (#5520): the comparisons' names live in the core's dialog
const FLT_CFT = ['select', 'checkbox', 'date', 'number', 'multiselect', 'currency', 'rating'];  // the field types the engine reads

const flt_live = id => { const l = listById(id); return l && !l.archived ? l : null; };
// the custom fields a condition can name: one per name + type over the visible projects
function flt_cfGroups() {
  const out = new Map();
  for (const fd of fieldsOn() ? S.fields || [] : []) {
    if (!FLT_CFT.includes(fd.type) || !flt_live(fd.list_id)) continue;
    const k = 'cf|' + fd.type + '|' + String(fd.name || '').trim().toLowerCase();
    if (!out.has(k)) out.set(k, {key: k, name: String(fd.name || '').trim(), ft: fd.type, fields: []});
    out.get(k).fields.push(fd);
  }
  const all = [...out.values()], dup = n => all.filter(g => g.name.toLowerCase() === n.toLowerCase()).length > 1;
  for (const g of all) g.label = dup(g.name) ? `${g.name} (${ftLabel(g.ft)})` : g.name;
  return all.sort((a, b) => cmpText(a.label, b.label));
}
// the key of a condition's "what" in the select
const flt_key = c => (c.f === 'cf' ? (c.fid ? 'cfid|' + c.fid : 'cf|' + c.ft + '|' + String(c.name || '').trim().toLowerCase()) : c.f);
const flt_ft = c => (c.f !== 'cf' ? null : c.fid ? fieldById(+c.fid)?.type : c.ft);
function flt_ops(c) {
  if (c.f === 'text') return ['has', 'nhas'];
  if (['list', 'prio', 'date', 'kind'].includes(c.f)) return ['in', 'nin'];  // 2.577.0 (#3354): + kind (every task has a state)
  if (c.f !== 'cf') return ['in', 'nin', 'empty'];
  const k = c.k || flt_cfKind(flt_ft(c));
  if (k === 'num') return ['gt', 'lt', 'eq', 'empty', ...(c.op === 'set' ? ['set'] : [])];
  if (k === 'chk') return ['in'];
  return ['in', 'nin', 'empty'];
}
const flt_isList = kflt_isList;
// the values a list condition offers: [value, label]; chosen values the list no longer has stay at the end
function flt_vals(c, cs, lid = 0) {
  const tasks = [...S.tasks.values()].filter(t => !t.deleted_at && flt_live(t.list_id));
  let o = [];
  switch (c.f) {
    case 'list': o = sideOrder().filter(l => !l.archived).map(l => [l.id, lname(l)]); break;
    case 'folder': o = folderNames().map(p => [p, fDisp(p)]); break;
    case 'date': o = DATE_OPTS.map(([v, n]) => [v, tr(n)]); break;
    case 'prio': o = [[7, tr('Urgent')], [5, tr('High')], [3, tr('Medium')], [1, tr('Low')], [0, tr('None')]]; break;  // 2.574.0 (#3376): + Urgent
    case 'type': o = [...TTYPES.map(([k, n]) => [k, tr(n)]), ...[...new Map(ttyRows().map(r => [r.key, r.name])).entries()].filter(([k]) => !TTYPES.some(x => x[0] === k)), ['', tr('No type')]]; break;  // 2.609.0 (#3372): + the own types
    case 'tag': o = [...new Set(tasks.flatMap(t => t.tags || []))].sort(cmpText).map(g => [g, '#' + g]); break;
    case 'who': {
      const ids = [...new Set(tasks.filter(t => t.assignee_id && t.assignee_id !== S.me?.id).map(t => t.assignee_id))];
      o = [['me', tr('Me')], ['none', tr('Nobody')], ...ids.map(id => [String(id), personNameAny(id) || '#' + id]).sort((a, b) => cmpText(a[1], b[1]))];
      break;
    }
    case 'sec': {  // the chosen projects' columns, else all
      const pick = lid ? [lid] : cs.filter(x => x.f === 'list' && x.op === 'in').flatMap(x => x.v || []);  // 2.577.0 (#3356): a shared view: its project's
      o = [...S.sections.filter(s => flt_live(s.list_id) && (!pick.length || pick.includes(s.list_id))).map(s => [String(s.id), `${lname(flt_live(s.list_id))} › ${s.name}`]), ['none', tr('No column')]];
      break;
    }
    case 'sprint': o = [['cur', tr('Current sprint')], ['none', tr('Backlog')]]; break;
    case 'ms': o = [...tasks.filter(t => t.ms).map(t => [String(t.id), t.title]), ['none', tr('No milestone')]]; break;
    case 'dlv': o = [...Object.entries(DV_NAMES).map(([k, n]) => [k, tr(n)]), ['none', tr('No delivery state')]]; break;
    case 'kind': o = SK_KINDS.map(([k]) => [k, sk_name(k)]); break;  // 2.577.0 (#3354)
    case 'cf': {
      const k = c.k || flt_cfKind(flt_ft(c));
      if (k === 'chk') o = [['1', tr('checked')], ['0', tr('not checked')]];
      else if (k === 'date') o = DATE_OPTS.map(([v, n]) => [v, tr(n)]);
      else if (c.fid) o = [...(fieldById(+c.fid)?.options?.options || []).map(x => [x.id, x.name]), ['', tr('empty')]];
      else {  // one entry per option name over the fields of that name
        const seen = new Set();
        for (const fd of (S.fields || []).filter(fd => flt_cfSame(fd, c))) for (const x of fd.options?.options || []) { const n = String(x.name || ''); if (n && !seen.has(n.toLowerCase())) { seen.add(n.toLowerCase()); o.push([n, n]); } }
        o.push(['', tr('empty')]);
      }
    }
  }
  const have = new Set(o.map(x => String(x[0])));
  for (const v of c.v || []) if (!have.has(String(v))) o.push([v, typeof v === 'number' ? '#' + v : String(v) || tr('empty')]);
  return o;
}
// a fresh condition for a "what" key
function flt_new(key) {
  if (key.startsWith('cfid|')) { const fd = fieldById(+key.slice(5)); const c = {f: 'cf', fid: fd?.id, op: 'in', v: []}; c.op = flt_ops(c)[0]; c.v = /** @type {any} */ (flt_isList(c) ? [] : ''); return c; }
  if (key.startsWith('cf|')) { const g = flt_cfGroups().find(x => x.key === key); const c = {f: 'cf', name: g?.name || '', ft: g?.ft || 'select', op: 'in', v: []}; c.op = flt_ops(c)[0]; c.v = /** @type {any} */ (flt_isList(c) ? [] : ''); return c; }
  return key === 'text' ? {f: 'text', op: 'has', v: ''} : {f: key, op: 'in', v: []};
}
// 2.846.0 (#5520): the tasks' catalog for the core's dialog (the rules part is FLT_TASKS of views.js); lid = a shared view
// (2.577.0 #3356): its project, no project / folder conditions
function flt_cat(lid = 0) {
  return {...FLT_TASKS,
    key: flt_key, ops: flt_ops, vals: (c, cs) => flt_vals(c, cs, lid), fresh: key => flt_new(key), add: () => (lid ? 'date' : 'list'),
    prep: () => flt_cfGroups(),
    // 2.577.0 (#3354): + the column meaning while a column has one
    what: c => { const sprOn = S.lists.some(l => !l.archived && spr_on(l)), kindOn = S.sections.some(s => s.kind && (!lid || s.list_id === lid)); return FLT_WHAT.filter(([k]) => k === c?.f || (k !== 'type' || ticketsAny()) && (k !== 'sprint' || sprOn) && (k !== 'kind' || kindOn) && (!lid || !['list', 'folder'].includes(k))); },
    extra: (c, cs, groups) => [...(groups || []).map(g => [g.key, g.label]), ...(c.fid ? (() => { const fd = fieldById(+c.fid); return fd ? [[flt_key(c), `${lname(listById(fd.list_id))} › ${fd.name}`]] : []; })() : [])],
    unit: c => (c.fid ? fieldById(+c.fid)?.options?.unit : null),
    keep: c => (c.f !== 'cf' || (c.fid ? fieldById(+c.fid) : true)) && (!lid || !['list', 'folder'].includes(c.f))};  // a condition of a gone field was off and stays out
}
// 2.577.0 (#3356): with lid the shared view of that project (S.views): no project / folder conditions (the view is its project),
// plus sort, grouping and display (listhead.js); everyone in the project sees it, its editors change it (the server decides)
function filterModal(id, lid = 0) {
  const f = id ? (lid ? S.views || [] : S.filters).find(x => x.id === id) : {name: '', rules: {}};
  if (!f) return;
  const r0 = f.rules && typeof f.rules === 'object' ? f.rules : {};
  const pick = (k, label, opts) => `<div class="row"><label for="f-${k}">${label}</label><select id="f-${k}">${opts.map(([v, n]) => `<option value="${v}" ${(r0[k] || '') === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>`;
  const vopts = !lid ? '' : `<div class="shint">${tr('Everyone in this project sees this view. Each person only sees the tasks they may see.')}</div>`
    + pick('sort', tr('Sorting'), [['', tr('As in the project')], ['prio', tr('Priority')], ['custom', tr('Manual only')], ['date', tr('Date')], ['title', tr('Title')], ['created', tr('Newest first')], ['created_asc', tr('Oldest first')]])
    + pick('group', tr('Grouping'), [['', tr('Column')], ['date', tr('Date')], ['person', tr('Person')], ['none', tr('No grouping')]])
    + (feat('kanban') || r0.display ? pick('display', tr('Display'), [['', tr('As in the project')], ['list', tr('List')], ['kanban', tr('Kanban')]]) : '');
  return kflt_dialog({cat: flt_cat(lid), rules: r0, name: f.name, more: vopts,  // more: HTML (kflt_dialog puts it as is)
    title: lid ? (id ? tr('Edit view') : tr('New shared view')) : id ? tr('Edit filter') : tr('New filter'),
    moreRules: md => (lid ? Object.fromEntries(['sort', 'group', 'display'].map(k => [k, $('#f-' + k, md)?.value || '']).filter(x => x[1])) : {}),
    // 2.577.0 (#3356): a view counts in its project
    count: rules => trn('{0} task matches', '{0} tasks match', openTasks().filter(t => !t.parent_id && (!lid || t.list_id === lid) && filterMatch(t, rules)).length),
    save: async (name, rules, md) => {
      if (lid) {  // 2.577.0 (#3356): the view opens in its project
        const j = id ? (await api('PATCH', '/api/filters/' + id, {name, rules}), {id}) : await api('POST', '/api/filters', {name, rules, list_id: lid});
        md.remove(); await load(); lv_pick(listById(lid), j.id); return;
      }
      if (id) { await api('PATCH', '/api/filters/' + id, {name, rules}); md.remove(); await load(); render(); }
      else { const j = await api('POST', '/api/filters', {name, rules}); md.remove(); await load(); go('f/' + j.id); }
    },
    del: id ? async md => {
      if (!await askConfirm(lid ? tr('Delete view “{0}”?', f.name) : tr('Delete filter “{0}”?', f.name), tr('Tasks are kept.'), {ok: tr('Delete'), danger: true})) return;
      await api('DELETE', '/api/filters/' + id); md.remove(); await load();
      if (lid) lv_pick(listById(lid), null); else go('today');  // 2.577.0 (#3356): back to the whole project
    } : null});
}
