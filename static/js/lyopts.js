/* Kalmido web client: the settings of a block in a view built from blocks (2.55.0, #1065).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.55.0 (#1065): a block can have a few settings of its own: the gear at the block in Customize and "Settings…" in its
// "…" menu open them (a small popover on a computer, a sheet on the phone). A view registers them in its own file or here:
//   lyo_reg(view, block, [{name, label, type, choices, default, when, apply}])
// type: bool | choice | number (choices [[value, label]] or [n, n]) | person | client | list | tag (picked from what the
// person sees; list may offer folders with folders: true, filter with pick: l => bool). when: () => false hides one,
// apply(x): runs after a change (e.g. a view state that mirrors it). Stored per person with the arrangement in
// opts[block][name] (accounts/layouts.py: bool, number or text up to 40 characters), so saved arrangements and
// "Standard for everyone" (wgMerge keeps the own switches) carry them. A block reads one with lyo_get(view, block, name):
// nothing set (or a list / client / person that is no longer visible) = its default = the behaviour before 2.55.
const LYO = {};
function lyo_reg(v, k, defs) { (LYO[v] ||= {})[k] = defs; }
const lyo_defs = (v, k) => (LYO[v]?.[k] || []).filter(d => !d.when || d.when());
const lyo_has = (v, k) => !!LY[v] && lyo_defs(v, k).length > 0;
const lyo_ch = d => (typeof d.choices === 'function' ? d.choices() : d.choices || []).map(c => Array.isArray(c) ? c : [c, String(c)]);
const lyo_tags = () => [...new Set([...S.tasks.values()].flatMap(t => t.tags || []))].filter(t => t.length <= 40).sort((a, b) => a.localeCompare(b, LOCALE()));
// the targets one can pick: only what this person sees right now
function lyo_src(d) {
  if (d.type === 'client') return (S.clients || []).map(c => [c.id, cdn_label(c)]);  // 2.97.0 B (#1951)
  if (d.type === 'person') return [...(S.me ? [[S.me.id, tr('Me')]] : []), ...teamPeople().map(p => [p.id, p.name])];
  if (d.type === 'tag') return lyo_tags().map(t => [t, '#' + t]);
  if (d.type === 'list') {
    const ls = S.lists.filter(l => !l.archived && !l.deleted_at && (!d.pick || d.pick(l)));
    const fs = d.folders ? [...new Set(ls.map(l => l.folder).filter(f => f && f.length <= 38))].sort((a, b) => a.localeCompare(b, LOCALE())).map(f => ['f:' + f, tr('Folder {0}', f)]) : [];
    return [...fs, ...ls.map(l => [l.id, lname(l)])];
  }
  return lyo_ch(d);
}
function lyo_ok(d, x) {
  if (x == null || x === '') return false;
  if (d.type === 'bool') return typeof x === 'boolean';
  return lyo_src(d).some(c => c[0] === x);
}
// the setting's value (its default when nothing valid is set); unknown settings give the raw value or def
function lyo_get(v, k, n, def) {
  const raw = LY[v] ? lyRaw(v).opts?.[k]?.[n] : undefined, d = (LYO[v]?.[k] || []).find(x => x.name === n);
  if (!d) return raw ?? def;
  return lyo_ok(d, raw) ? raw : d.default ?? def;
}
const lyo_val = (v, k, n) => LY[v] ? lyRaw(v).opts?.[k]?.[n] : undefined;
// a list setting with folders: does list l belong to the picked one
const lyo_inList = (x, l) => x == null || (typeof x === 'string' && x.startsWith('f:') ? l?.folder === x.slice(2) : l?.id === x);
// one undoable change of the person's own settings of block k (null = back to the default); the own value only, so an
// arrangement that follows the standard for everyone keeps following it
function lyo_put(v, k, ch, msg) {
  const d = LY[v]; if (!d) return;
  const before = d.src ? lyRaw(v) : wgJ(LY_PEND[d.key] ?? S.settings?.[d.key]), b = JSON.stringify(before), o = JSON.parse(b);
  const bo = {...(o.opts?.[k] || {})};
  for (const [n, x] of Object.entries(ch)) { if (x == null) delete bo[n]; else bo[n] = x; }
  if (Object.keys(bo).length) (o.opts ||= {})[k] = bo; else if (o.opts) { delete o.opts[k]; if (!Object.keys(o.opts).length) delete o.opts; }
  const a = JSON.stringify(o); if (a === b) return;
  const put = s => () => { const y = JSON.parse(s); lyStore(v, Object.keys(y).length ? y : '', false); lyo_applied(v, k); lyo_redraw(); return {}; };
  put(a)();
  histToast(msg || tr('Setting changed'), histAdd({label: msg || tr('Setting changed'), undo: put(b), redo: put(a)}));
}
function lyo_applied(v, k) { for (const d of lyo_defs(v, k)) d.apply?.(lyo_get(v, k, d.name)); }

// ---- the gear (Customize) and the menu entry
const lyo_gear = (v, k) => {
  if (!lyo_has(v, k)) return '';
  const nm = tr(lyBlocks(v).find(b => b[0] === k)?.[1] || k);
  return `<button type="button" class="iconbtn lyo-gear" data-act="lyo-open" data-lyv="${v}" data-k="${k}" aria-haspopup="dialog" title="${esc(tr('Settings: {0}', nm))}" aria-label="${esc(tr('Settings: {0}', nm))}">${ic('gear', 's')}</button>`;
};
const lyo_items = (v, k, a) => lyo_has(v, k) ? [{label: tr('Settings…'), icon: 'gear', fn: () => lyo_open(v, k, a)}] : [];

// ---- the popover / sheet
let LYO_OPEN = null;  // {v, k} while open
function lyo_row(v, k, d) {
  const id = `lyo-${k}-${d.name}`, lab = `<span class="lyo-l" id="${id}">${esc(tr(d.label))}</span>`, x = lyo_val(v, k, d.name), cur = lyo_get(v, k, d.name);
  if (d.type === 'bool') return `<div class="lyo-r lyo-b">${lab}<label class="swc"><input type="checkbox" data-lyo="${esc(d.name)}" aria-labelledby="${id}" ${cur ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></label></div>`;
  if (d.type === 'choice' || d.type === 'number') {
    return `<div class="lyo-r">${lab}<div class="seg lyo-seg" role="group" aria-labelledby="${id}">${lyo_ch(d).map(([c, l], i) => `<button type="button" data-lyo="${esc(d.name)}" data-x="${i}" class="${c === cur ? 'on' : ''}" aria-pressed="${c === cur}">${esc(tr(l))}</button>`).join('')}</div></div>`;
  }
  const src = lyo_src(d), gone = x != null && x !== '' && !src.some(c => c[0] === x);
  return `<div class="lyo-r">${lab}<select data-lyo="${esc(d.name)}" aria-labelledby="${id}"><option value="">${esc(tr(d.all || 'All'))}</option>${gone ? `<option value="__gone" selected disabled>${esc(tr('No longer available'))}</option>` : ''}${src.map(([c, l]) => `<option value="${esc(String(c))}" ${c === cur ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>${gone ? `<span class="muted lyo-gone">${esc(tr('The chosen one is no longer available; the block shows everything.'))}</span>` : ''}</div>`;
}
function lyo_body(v, k) {
  const own = lyo_defs(v, k).some(d => lyo_val(v, k, d.name) != null);
  return lyo_defs(v, k).map(d => lyo_row(v, k, d)).join('') + (own ? `<button type="button" class="linkbtn lyo-reset" data-lyo-reset="1">${tr('Back to the default')}</button>` : '');
}
function lyo_open(v, k, anchor) {
  const b = LY[v] && lyBlocks(v).find(x => x[0] === k); if (!b || !lyo_has(v, k)) return;
  const t = tr('Settings: {0}', tr(b[1]));
  LYO_OPEN = {v, k};
  const p = openPop(anchor, `${isMobile() ? tch_sheetHead(t) : `<div class="lyo-h">${ic('gear', 's')}<b>${esc(t)}</b></div>`}<div class="lyo" role="group" aria-label="${esc(t)}" data-lyov="${v}" data-lyok="${k}">${lyo_body(v, k)}</div>`, () => { LYO_OPEN = null; });
  setTimeout(() => { if (!p.classList.contains('hidden')) $('.lyo [data-lyo]', p)?.focus({preventScroll: true}); }, 0);
}
// after a change (or its undo): the open popover shows the new values, the focus stays on the same control
function lyo_redraw() {
  const box = $('#pop:not(.hidden) .lyo'); if (!box || !LYO_OPEN) return;
  const f = document.activeElement, fk = box.contains(f) ? [f.dataset.lyo, f.dataset.x, f.dataset.lyoReset] : null;
  box.innerHTML = lyo_body(LYO_OPEN.v, LYO_OPEN.k);
  if (fk) (box.querySelector(fk[2] ? '[data-lyo-reset]' : `[data-lyo="${CSS.escape(fk[0] || '')}"]${fk[1] != null ? `[data-x="${fk[1]}"]` : ''}`) || box.querySelector('[data-lyo]'))?.focus({preventScroll: true});
}
function lyo_change(el) {
  const box = el.closest('.lyo'), v = box?.dataset.lyov, k = box?.dataset.lyok; if (!LY[v]) return;
  if (el.dataset.lyoReset) { lyo_put(v, k, Object.fromEntries(lyo_defs(v, k).map(d => [d.name, null])), tr('Settings reset')); return; }
  const d = lyo_defs(v, k).find(x => x.name === el.dataset.lyo); if (!d) return;
  let x;
  if (d.type === 'bool') x = !!el.checked;
  else if (d.type === 'choice' || d.type === 'number') x = lyo_ch(d)[+el.dataset.x]?.[0];
  else x = el.value === '' ? null : lyo_src(d).find(c => String(c[0]) === el.value)?.[0];
  if (x === undefined || el.value === '__gone') return;
  lyo_put(v, k, {[d.name]: x}, tr(d.label) + ': ' + (d.type === 'bool' ? (x ? tr('on') : tr('off')) : x == null ? tr(d.all || 'All') : (d.type === 'choice' || d.type === 'number' ? tr(lyo_ch(d).find(c => c[0] === x)[1]) : lyo_src(d).find(c => c[0] === x)[1])));
}
document.addEventListener('click', e => {
  const g = e.target.closest?.('[data-act="lyo-open"]');
  if (g) { e.preventDefault(); e.stopPropagation(); lyo_open(g.dataset.lyv, g.dataset.k, g); return; }
  const b = e.target.closest?.('#pop .lyo button[data-lyo], #pop .lyo [data-lyo-reset]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); lyo_change(b);
}, true);
document.addEventListener('change', e => { const t = e.target.closest?.('#pop .lyo input[data-lyo], #pop .lyo select[data-lyo]'); if (t) lyo_change(t); });

// ---- the settings of the views that are on the builder (new views register in their own files)
// the start page (dashboard.js dashCard)
lyo_reg('home', 'today', [
  {name: 'n', label: N_('Number of tasks'), type: 'number', choices: [5, 8, 10, 20], default: 8},
  {name: 'mine', label: N_('Only tasks assigned to me'), type: 'bool', default: false, when: () => collab()},
  {name: 'list', label: N_('Only this list or folder'), type: 'list', folders: true, default: null}]);
lyo_reg('home', 'projects', [
  {name: 'active', label: N_('Only active projects'), type: 'bool', default: true},
  {name: 'sort', label: N_('Order'), type: 'choice', choices: [['side', N_('As in the sidebar')], ['name', N_('By name')], ['progress', N_('By progress')]], default: 'side'},
  {name: 'n', label: N_('Number of projects'), type: 'number', choices: [5, 10, 20], default: 5}]);
lyo_reg('home', 'pinned', [{name: 'n', label: N_('Number of tasks'), type: 'number', choices: [6, 10, 20], default: 6}]);
lyo_reg('home', 'news', [{name: 'n', label: N_('Number of entries'), type: 'number', choices: [5, 10], default: 5}]);
lyo_reg('home', 'kpi', [
  {name: 'rev', label: N_('Revenue this month'), type: 'bool', default: true},
  {name: 'open', label: N_('Open invoices'), type: 'bool', default: true},
  {name: 'over', label: N_('Overdue|invoices'), type: 'bool', default: true},
  {name: 'pipe', label: N_('Pipeline, weighted'), type: 'bool', default: true}]);
// time tracking (time.js viewTime): each block of the report can show one client or one list only (the report is filtered
// in the browser: the entries are loaded anyway)
const lyo_tvScope = () => [
  {name: 'client', label: N_('Only this client'), type: 'client', default: null, when: () => (S.clients || []).length > 0},
  {name: 'list', label: N_('Only this project or list'), type: 'list', default: null}];
lyo_reg('time', 'tiles', lyo_tvScope());
lyo_reg('time', 'chart', [...lyo_tvScope(), {name: 'kind', label: N_('Chart'), type: 'choice', choices: [['bar', N_('Bars')], ['line', N_('Line|chart')]], default: 'bar'}]);
lyo_reg('time', 'lists', lyo_tvScope());
lyo_reg('time', 'entries', [...lyo_tvScope(), {name: 'open', label: N_('Show the entries unfolded'), type: 'bool', default: false,
  apply: x => { if (S.tv && S.tv.entries !== !!x) { S.tv.entries = !!x; LS.set('timeEntries', S.tv.entries); renderView(); } }}]);
// the projects overview (projects.js viewOverview) and the agents overview (agents.js viewAgents)
lyo_reg('projects', 'projects', [
  {name: 'sort', label: N_('Order'), type: 'choice', choices: [['risk', N_('Needs attention first')], ['name', N_('By name')], ['overdue', N_('Most overdue first')]], default: 'risk'},
  {name: 'active', label: N_('Only active projects'), type: 'bool', default: false},
  {name: 'n', label: N_('Number of projects'), type: 'number', choices: [[0, N_('All')], [5, '5'], [10, '10'], [20, '20']], default: 0}]);
lyo_reg('agents', 'agents', [
  {name: 'on', label: N_('Only switched-on agents'), type: 'bool', default: false},
  {name: 'sort', label: N_('Order'), type: 'choice', choices: [['std', N_('As set up')], ['name', N_('By name')], ['need', N_('Needs a look first')]], default: 'std'}]);

// ---- helpers for the blocks
// time tracking: the report of one block (only the entries of the chosen client / list), same shape as the server's
// (personal/timetrack.py time_report); null = the whole report
function lyo_tvReport(j, k) {
  const cid = lyo_get('time', k, 'client'), lid = lyo_get('time', k, 'list');
  if (!j || (cid == null && lid == null)) return null;
  const cl = cid != null ? clientById(cid) : null, inC = new Set(cl?.lists || []);
  const es = j.entries.filter(e => (cid == null || inC.has(e.list_id)) && (lid == null || e.list_id === lid));
  const base = Object.fromEntries(j.lists.map(l => [l.id, l])), L = new Map(), D = {}, t0 = today();
  const tot = {seconds: 0, rounded: 0, amount: 0, count: 0};
  const add = (x, e) => { x.seconds += e.seconds; x.rounded += e.rounded; x.amount = (x.amount || 0) + (e.amount || 0); };
  for (const e of es) {
    add(tot, e); tot.count++;
    const id = base[e.list_id] ? e.list_id : 0, b = base[id] || {id: 0, name: '', rate: null};
    if (!L.has(id)) L.set(id, {...b, seconds: 0, rounded: 0, amount: 0, tasks: new Map(), users: {}});
    const g = L.get(id); add(g, e); g.users[e.user_name] = (g.users[e.user_name] || 0) + e.rounded;
    const tk = e.task_id || 'x:' + e.title;
    if (!g.tasks.has(tk)) g.tasks.set(tk, {id: e.task_id, title: e.title, seconds: 0, rounded: 0, amount: 0, users: {}});
    const x = g.tasks.get(tk); add(x, e); x.users[e.user_name] = (x.users[e.user_name] || 0) + e.rounded;
    (D[e.day] ||= {date: e.day, seconds: 0, rounded: 0}); D[e.day].seconds += e.seconds; D[e.day].rounded += e.rounded;
  }
  const us = o => Object.entries(o).sort((a, b) => b[1] - a[1]);
  const lists = [...L.values()].map(g => ({...g, amount: Math.round(g.amount * 100) / 100, users: us(g.users),
    tasks: [...g.tasks.values()].map(x => ({...x, users: us(x.users)})).sort((a, b) => b.seconds - a.seconds || String(a.title).localeCompare(String(b.title)))}))
    .sort((a, b) => b.seconds - a.seconds);
  tot.amount = Math.round(tot.amount * 100) / 100;
  const mine = es.filter(e => e.user_id === S.me?.id && e.day === t0).reduce((n, e) => n + e.seconds, 0);
  return {...j, total: tot, lists, entries: es, days: Object.values(D).sort((a, b) => a.date.localeCompare(b.date)), today: {...j.today, seconds: mine},
    lyoLabel: [cl && cl.name, lid != null && lname(listById(lid))].filter(Boolean).join(' · ')};
}
const lyo_note = txt => txt ? `<p class="muted lyo-note">${ic('filter', 's')}<span>${esc(tr('Only: {0}', txt))}</span></p>` : '';
