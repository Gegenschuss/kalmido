/* Kalmido web client: Undo / redo history.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ undo / redo history (D4)
// Per device and session, in memory only (gone after a reload): up to HIST_MAX steps back (the ← button, Ctrl/Cmd+Z,
// the toast's "Undo") and forward again (→, Ctrl/Cmd+Shift+Z, Ctrl+Y); a right-click / long-press on ← (or →) lists
// the last steps to jump several at once. A new action clears the steps forward. A step has a label, how to go back and
// forth (undo(e) / redo(e) -> {skipped, q, none}) and the task copies from before (snaps) and after (after).
// Conflict safety: task fields carry _prev (the values the step left), sections / lists their expected state, so a change
// made elsewhere in the meantime stays and is reported ("Changed elsewhere, not undone: …"); every task step goes to
// /api/tasks/batch, one transaction however many tasks it touches. Offline: a step whose operation still waits in the
// outbox is taken out of the queue and the local state restored (never sent); otherwise task steps are queued like
// any other change (the buttons show the pending state). Steps on lists that became view-only refuse.
const UNDO_FIELDS = ['list_id', 'section_id', 'parent_id', 'due', 'due_time', 'start', 'duration', 'reminders', 'repeat', 'repeat_from', 'priority', 'pinned', 'assignee_id', 'ttype', 'deadline', 'nag', 'assignee_group_id', 'plan_start', 'ms', 'milestone_id'];  // 2.18.0: ms, milestone_id (#430)  // 2.11.0: plan_start  // 2.10.0: assignee_group_id  // 2.4.0: ttype (#340), 2.7.0: deadline, nag
const HIST_FIELDS = [...UNDO_FIELDS, 'title', 'content', 'url', 'tags', 'fields'];
const HIST_MAX = 30, HIST_MENU = 10;
const HIST = {undo: [], redo: [], busy: false, group: null, gToast: null, toastE: null, sess: 0, ids: {}, secmap: new Map()};
const snapTask = t => t ? JSON.parse(JSON.stringify(t)) : null;
const withKids = id => { const out = [], walk = x => { for (const k of children(x)) { out.push(snapTask(k)); walk(k.id); } }; out.push(snapTask(taskById(id))); walk(id); return out.filter(Boolean); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const rid = id => (+id < 0 && HIST.ids[id]) || +id;  // a task created offline: its real id once the outbox was sent
const secId = sid => { let s = sid; for (let i = 0; i < 50 && s && HIST.secmap.has(s); i++) s = HIST.secmap.get(s); return s; };  // re-created sections
const cancellable = e => { const i = OUT.q.indexOf(e); return i >= 0 && !(OUT.flushing && i === 0); };
const histPending = e => !!e && (e.parts ? e.parts.some(histPending) : !!(e.q && !e.q.done && OUT.q.includes(e.q)));
const nv = v => v === '' || v === undefined ? null : v;
const qn = s => tr('“{0}”', s);  // a name in quotes, as the language writes them
// field changes: reverse of what actually changed; _prev = the values after, so a change made elsewhere in the
// meantime is not overwritten (reported instead). reverseOf(after, before) is the way forward again.
function reverseOf(before, after, fields = UNDO_FIELDS) {
  const back = {}, prev = {};
  for (const k of fields) {
    if (k === 'fields') {
      const bf = before.fields || {}, af = after.fields || {}, fb = {}, fp = {};
      for (const f of new Set([...Object.keys(bf), ...Object.keys(af)])) if (nv(bf[f]) !== nv(af[f])) { fb[f] = nv(bf[f]); fp[f] = nv(af[f]); }
      if (Object.keys(fb).length) { back.fields = fb; prev.fields = fp; }
      continue;
    }
    if (!(k in before) && !(k in after)) continue;
    const arr = k === 'tags' || k === 'ltags';  // 2.26.0 (#936): list tags too (the multi panel adds / removes them)
    const a = arr ? [...(before[k] || [])].sort().join('\u0001') : nv(before[k]), b = arr ? [...(after[k] || [])].sort().join('\u0001') : nv(after[k]);
    if (a !== b) { back[k] = arr ? [...(before[k] || [])] : nv(before[k]); prev[k] = arr ? [...(after[k] || [])] : nv(after[k]); }
  }
  return Object.keys(back).length ? {...back, _prev: prev} : null;
}
// ---- building steps
function histAdd(e) {
  e.snaps = e.snaps || [];
  const ids = [...new Set([...e.snaps.map(s => s.id), ...(e.ids || [])])];
  if (!e.after) e.after = ids.map(id => snapTask(S.tasks.get(id)) || {id, _gone: true});
  e.lids = [...new Set([...(e.lids || []), ...e.snaps.map(s => s.list_id), ...e.after.map(s => s.list_id)].filter(Boolean))];
  if (e.q === undefined) e.q = e.res?._q || null;
  if (HIST.group) { HIST.group.push(e); return e; }
  HIST.undo.push(e);
  if (HIST.undo.length > HIST_MAX) HIST.undo.shift();
  HIST.redo = [];
  if (HIST.toastE && HIST.toastE !== e) { HIST.toastE = null; $('#toast')?.classList.add('hidden'); }  // the old toast would undo the wrong step
  renderHist();
  return e;
}
// several recorded steps of one user action (e.g. a drop that makes a subtask standalone and moves it) become one
async function histGroup(fn, label) {
  if (HIST.group) return fn();
  const g = HIST.group = [];
  HIST.gToast = null;
  try { return await fn(); } finally {
    HIST.group = null;
    const msg = HIST.gToast; HIST.gToast = null;
    const e = g.length === 1 ? g[0] : g.length ? {label: label || g[g.length - 1].label, parts: g, snaps: [], after: [], q: null, lids: g.flatMap(x => x.lids)} : null;
    if (e) { e.group = true; histAdd(e); if (msg) histToast(msg, e); }
  }
}
// the toast with "Undo" for a step (a shortcut to the newest history entry)
function histToast(msg, e) {
  if (!e) { toast(msg); return; }
  if (HIST.group && HIST.group.includes(e)) { HIST.gToast = msg; return; }
  toast(msg, () => { if (HIST.undo[HIST.undo.length - 1] === e) histStep('undo'); }, 6000);
  HIST.toastE = e;
}
// task field steps: [before, after, fields?] per task -> one batch request each way
function histFields(label, pairs, o = {}) {
  pairs = pairs.filter(p => p[0] && p[1] && reverseOf(p[0], p[1], p[2] || o.fields || HIST_FIELDS));
  if (!pairs.length) return null;
  const go = back => () => {
    const items = {};
    for (const [b, a, f] of pairs) { const x = back ? reverseOf(b, a, f || o.fields || HIST_FIELDS) : reverseOf(a, b, f || o.fields || HIST_FIELDS); if (x) items[b.id] = x; }
    return histBatch('patch_each', Object.keys(items), {items});
  };
  return histAdd({label, pairs, undo: go(true), redo: go(false), snaps: pairs.map(p => p[0]), after: pairs.map(p => ({...(snapTask(S.tasks.get(p[1].id)) || {}), ...p[1]})),
    res: o.res, lids: pairs.flatMap(p => [p[0].list_id, p[1].list_id]), text: o.text, sess: o.sess});
}
// completion / won't do (status) of ids; res = the answer of the forward request (signed undo payloads)
function histDone(label, ids, snaps, res, status = 2) {
  const toks = r => { const u = r?.undo; return !u ? {} : u.sig ? {[ids[0]]: u} : u; };
  const expect = Object.fromEntries(ids.map(id => [id, snaps.find(s => s.id === id)?.due ?? null]));
  return histAdd({label, snaps, ids, res,
    undo: e => { const t = toks(e.res); return Object.keys(t).length ? histBatch('undo', Object.keys(t), {items: t}) : {skipped: [], none: true}; },
    redo: async e => { const r = await histBatch('complete', ids, {status, expect}); e.res = r.res; return r; }});
}
// reopened (a done task back to open): undo = complete it again with its old completion data
function histReopen(label, id, snaps, res) {
  return histAdd({label, snaps, ids: [id], res,
    undo: e => { const u = e.res?.undo; return !u ? {skipped: [], none: true} : histBatch('undo', [id], {items: {[id]: u.sig ? u : u[id]}}); },
    redo: async e => { const r = await histBatch('reopen', [id], {}); e.res = r.res; return r; }});
}
// moved to the trash; the way forward again only while nobody else changed them after the undo
function histTrash(label, ids, snaps, res) {
  return histAdd({label, snaps, ids, res,
    undo: async e => { const r = await histBatch('restore', ids, {}); e.since = r.res?.now; return r; },
    redo: e => histBatch('delete', ids, e.since ? {guard: Object.fromEntries(ids.map(i => [i, e.since]))} : {})});
}
// created: undo = to the trash (not if someone else changed it since), redo = back from the trash
function histCreate(label, t, extra = {}) {
  const id = t.id;
  return histAdd({label, snaps: [{id, _gone: true}], ids: [id], res: t, lids: [t.list_id], ...extra,
    undo: e => { const since = e.since || e.res?.created_at; return histBatch('delete', [id], since ? {guard: {[id]: since}} : {}); },
    redo: async e => { const r = await histBatch('restore', [id], {}); e.since = r.res?.now; return r; }});
}
// ---- sending
const histFieldName = f => f.startsWith('field:') ? fieldById(+f.slice(6))?.name || tr('Custom field') : FIELD_NAMES[f] ? tr(FIELD_NAMES[f]) : {status: tr('Status'), changed: tr('changed by someone else'), order: tr('Order'), name: tr('Name'), section: tr('Section'), folder: tr('Folder')}[f] || f;
const histTitle = (id, t) => qn(String(t || S.tasks.get(rid(id))?.title || '').slice(0, 30));
async function histBatch(action, ids, data) {
  const d = {...data};
  for (const k of ['items', 'expect', 'guard']) {
    if (d[k]) d[k] = Object.fromEntries(Object.entries(d[k]).map(([id, v]) => [rid(id), k === 'items' && action === 'patch_each' ? histSecFix(v) : v]));
  }
  const r = await api('POST', '/api/tasks/batch', {ids: ids.map(rid), action, data: d});
  const cf = r?.conflicts || [];
  const skipped = cf.length ? cf.map(c => `${histTitle(c.id, c.title)}: ${histFieldName(c.field)}`) : (r?.errors || []);
  return {res: r, q: r?._q || null, skipped, none: !r?._q && r?.count === 0 && !!(cf.length || r?.errors?.length)};
}
function histSecFix(v) {
  const o = {...v};
  if (o.section_id) o.section_id = secId(o.section_id);
  if (o._prev && o._prev.section_id) o._prev = {...o._prev, section_id: secId(o._prev.section_id)};
  return o;
}
// local copies back (outbox cancelled / queued offline): merged, so partial copies (dates only) keep the rest
function histLocal(state) {
  for (const s of state || []) {
    const id = rid(s.id);
    if (s._gone) S.tasks.delete(id);
    else if (s.title !== undefined || S.tasks.has(id)) S.tasks.set(id, {...(S.tasks.get(id) || {}), ...snapTask(s), id});
  }
}
async function histRun(e, dir) {
  if (e.parts) {
    const out = {skipped: [], queued: false};
    for (const p of dir === 'undo' ? [...e.parts].reverse() : e.parts) { const r = await histRun(p, dir); out.skipped.push(...r.skipped); out.queued = out.queued || r.queued; }
    return out;
  }
  const q = e.q;
  if (q) {  // the last operation of this step went through the outbox: cancel it if it has not left yet, else wait for its answer
    for (let n = 0; n < 400 && !q.done && !cancellable(q); n++) await sleep(150);
    if (!q.done && cancellable(q)) {
      OUT.q.splice(OUT.q.indexOf(q), 1); LS.set('outbox', OUT.q);
      histLocal(dir === 'undo' ? e.snaps : e.after);
      e.q = null; renderTop();
      return {skipped: [], local: true};
    }
    e.q = null;
    if (q.done && q.res) e.res = q.res;
  }
  const r = await e[dir](e) || {};
  if (r.q) { e.q = r.q; histLocal(dir === 'undo' ? e.snaps : e.after); }  // queued offline: show where it is going
  return {skipped: r.skipped || [], queued: !!r.q, none: !!r.none};
}
// n steps back (undo) or forward (redo), one after the other
async function histStep(dir, n = 1) {
  if (HIST.busy) return;
  HIST.busy = true; renderHist();
  const done = [], skipped = [];
  let queued = false, stop = false, dropped = null;
  try {
    await flushSaves();
    for (let i = 0; i < n && !stop; i++) {
      const from = HIST[dir], e = from[from.length - 1]; if (!e) break;
      if (e.lids.some(l => listById(l) && !canAddTo(l))) {  // the list became view-only in the meantime (participants: the server checks each task)
        from.pop(); stop = true;
        toast(dir === 'undo' ? tr('View only: “{0}” can no longer be undone', e.label) : tr('View only: “{0}” can no longer be redone', e.label));
        break;
      }
      let r;
      try { r = await histRun(e, dir); } catch (x) {
        if (!(x instanceof Offline) && x.message !== 'auth') { from.pop(); dropped = e; }  // gone or no rights: api() said why
        stop = true; break;
      }
      from.pop();
      if (r.none && !r.skipped.length) r.skipped.push(e.label);
      if (r.none) dropped = e;  // nothing could be applied (changed elsewhere): out of the history
      else HIST[dir === 'undo' ? 'redo' : 'undo'].push(e);
      done.push(e); skipped.push(...r.skipped); queued = queued || r.queued;
      if (r.none) stop = true;
    }
  } finally {
    try {  // the page may be gone meanwhile (closed tab, tests)
      if (done.length || dropped) {
        if (OUT.online && !OUT.q.length) await load().catch(() => {});
        render();
        if (S.sel) { if (taskById(S.sel)) renderDetail(); else closeDetail(); }
        for (const x of done) { try { x.post?.(dir); } catch (err) { console.warn('history post', err); } }
      }
      if (done.length) {
        if (skipped.length) toast((dir === 'undo' ? tr('Changed elsewhere, not undone: {0}', skipped.slice(0, 4).join(', ')) : tr('Changed elsewhere, not redone: {0}', skipped.slice(0, 4).join(', '))) + (skipped.length > 4 ? ' …' : ''));
        else {
          const what = done.length > 1 ? (dir === 'undo' ? trn('{0} step undone', '{0} steps undone', done.length) : trn('{0} step redone', '{0} steps redone', done.length))
            : dir === 'undo' ? tr('Undone: {0}', done[0].label) : tr('Redone: {0}', done[0].label);
          toast(queued ? what + ' · ' + tr('sent as soon as you are online') : what);
        }
      }
    } catch (x) { console.warn('history', x); }
    HIST.busy = false;
    try { renderHist(); } catch { /* page gone */ }
  }
}
// ---- the ← / → buttons (top bar), their tooltips and the history menu
function histBtn(dir) {
  const e = HIST[dir][HIST[dir].length - 1], p = histPending(e);
  const lab = e ? (dir === 'undo' ? tr('Undo: {0}', e.label) : tr('Redo: {0}', e.label)) : dir === 'undo' ? tr('Nothing to undo') : tr('Nothing to redo');
  return {lab, tip: lab + (e ? ` (${kbText(dir === 'undo' ? 'Mod+Z' : 'Mod+Shift+Z')})` : '') + (p ? ' · ' + tr('waiting for the connection') : ''), off: !e || HIST.busy, p};
}
function histBtns() {
  return `<div class="hist tf" role="group" aria-label="${esc(tr('History'))}">${['undo', 'redo'].map(dir => { const b = histBtn(dir); return `<button type="button" class="iconbtn hbtn${b.p ? ' pend' : ''}" data-act="hist-${dir}" aria-label="${esc(b.lab)}" title="${esc(b.tip)}"${b.off ? ' disabled' : ''}>${ic(dir === 'undo' ? 'undo' : 'redo')}</button>`; }).join('')}</div>`;
}
function renderHist() {  // in place: keeps the keyboard focus on the button
  for (const dir of ['undo', 'redo']) {
    const el = $(`#top [data-act="hist-${dir}"]`); if (!el) continue;
    const b = histBtn(dir);
    el.disabled = b.off; el.title = b.tip; el.setAttribute('aria-label', b.lab); el.classList.toggle('pend', b.p);
  }
}
function histMenu(anchor, dir) {
  const list = HIST[dir].slice(-HIST_MENU).reverse();
  if (!list.length || HIST.busy) return;
  $('#toast')?.classList.add('hidden');
  menu(anchor, list.map((e, i) => ({label: e.label, icon: dir === 'undo' ? 'undo' : 'redo', cls: 'hitem' + (histPending(e) ? ' pend' : ''), fn: () => histStep(dir, i + 1)})));
  const p = $('#pop');
  if (p) {
    p.querySelector('.menu-list')?.insertAdjacentHTML('afterbegin', `<div class="hhead">${esc(dir === 'undo' ? tr('Undo up to here') : tr('Redo up to here'))}</div>`);
    p.querySelector('.menu-list')?.setAttribute('aria-label', dir === 'undo' ? tr('Undo history') : tr('Redo history'));
  }
}
document.addEventListener('contextmenu', e => {
  const b = e.target.closest?.('#top [data-act^="hist-"]'); if (!b) return;
  e.preventDefault(); histMenu(b, b.dataset.act.slice(5));
});
let histHold = null;
document.addEventListener('touchstart', e => {
  const b = e.target.closest?.('#top [data-act^="hist-"]'); if (!b) return;
  clearTimeout(histHold?.t);
  histHold = {b, fired: false, t: setTimeout(() => { if (histHold) { histHold.fired = true; if (navigator.vibrate) navigator.vibrate(10); histMenu(b, b.dataset.act.slice(5)); } }, 450)};
}, {passive: true});
document.addEventListener('touchmove', () => { if (histHold && !histHold.fired) { clearTimeout(histHold.t); histHold = null; } }, {passive: true});
document.addEventListener('touchend', e => { if (!histHold) return; clearTimeout(histHold.t); if (histHold.fired && e.cancelable) e.preventDefault(); const h = histHold; setTimeout(() => { if (histHold === h) histHold = null; }, 400); });
const histHeld = () => !!histHold?.fired;
// keyboard: Ctrl/Cmd+Z back, Ctrl/Cmd+Shift+Z or Ctrl+Y forward -- never while typing (the browser's own text undo)
const isTextEl = el => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !/^(checkbox|radio|button|submit|reset|range|color|file|image)$/i.test(el.type || '')));
document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const k = (e.key || '').toLowerCase(), redo = (k === 'z' && e.shiftKey) || (k === 'y' && e.ctrlKey && !e.metaKey && !e.shiftKey);
  if (k !== 'z' && !redo) return;
  if (isTextEl(e.target) || isTextEl(document.activeElement) || $('.modal')) return;
  e.preventDefault();
  histStep(redo ? 'redo' : 'undo');
});
// what a field change did, for the history ("Priority of “Pay invoice”: High")
function histLabel(b, a) {
  const n = qn(String(a.title || b.title || '').slice(0, 40)), ch = HIST_FIELDS.filter(k => reverseOf(b, a, [k]));
  const has = k => ch.includes(k);
  if (has('list_id')) return tr('Moved {0} to {1}', n, lname(listById(a.list_id)) || '?');
  if (has('parent_id')) return a.parent_id ? tr('{0} is now a subtask', n) : tr('{0} is now a main task', n);
  if (ch.length === 1 && has('title')) return tr('Renamed {0}', n);
  if (ch.length === 1 && has('content')) return tr('Description of {0}', n);
  if (ch.length === 1 && has('priority')) return tr('Priority of {0}: {1}', n, tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High')][+a.priority || 0] || N_('None')));
  if (ch.length === 1 && has('tags')) return tr('Tags of {0}', n);
  if (ch.length === 1 && has('assignee_id')) return a.assignee_id ? tr('{0} assigned to {1}', n, personName(a.list_id, a.assignee_id) || '?') : tr('{0} unassigned', n);
  if (ch.length === 1 && has('fields')) { const f = Object.keys(reverseOf(b, a, ['fields']).fields); return f.length === 1 ? tr('{0} of {1}', fieldById(+f[0])?.name || tr('Custom field'), n) : tr('Custom fields of {0}', n); }
  if (ch.length === 1 && has('pinned')) return a.pinned ? tr('Pinned {0}', n) : tr('Unpinned {0}', n);
  if (ch.length === 1 && has('url')) return tr('Link of {0}', n);
  if (ch.length === 1 && has('section_id')) return tr('Moved {0} to section {1}', n, secName(a.section_id));
  if (has('plan_start') && !has('due')) return a.plan_start ? tr('Planned {0}', n) : tr('Unplanned {0}', n);  // 2.11.0
  if (has('due') || has('start') || has('due_time')) return a.due ? tr('Date of {0}: {1}', n, dayLabel(a.due)) : tr('Date of {0} removed', n);
  if (has('repeat') || has('repeat_from')) return tr('Repeat of {0}', n);
  if (has('reminders')) return tr('Reminder of {0}', n);
  return tr('Edited {0}', n);
}
// the few older callers: a toast with "Undo" for a step built above
function offerUndo(msg, e) { histToast(msg, e); }
async function patchUndoable(id, body, msg) {
  const before = snapTask(taskById(id));
  const t = await patchTask(id, body, true);
  if (t?.shifted?.length) { shiftUndo(before, t, msg); return t; }
  const after = snapTask(S.tasks.get(id) || t);
  const e = before && after && histFields(histLabel(before, after), [[before, after]], {res: t});
  if (e) offerUndo(msg, e);
  else if (msg) toast(msg);
  return t;
}
async function toggleTask(id) {
  const t = taskById(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  const snaps = withKids(id), n = qn(t.title.slice(0, 40));
  if (t.status !== 0) {
    const r = await api('POST', `/api/tasks/${id}/reopen`);
    const {undo, ...rt} = r; putTask(rt);
    if (S.extra) S.extra = S.extra.filter(x => x.id !== id);
    render();
    offerUndo(tr('Reopened {0}', n), histReopen(tr('Reopened {0}', n), id, snaps, r));
    return;
  }
  if (t.blocked && dFor(t) && !await askConfirm(tr('“{0}” is still blocked by {1}. Complete it anyway?', t.title, blockedNames(t)), '', {ok: tr('Complete anyway')})) return;
  // optimistic: fade the row, then sync
  $$(`.trow[data-id="${id}"] .chk`).forEach(c => { c.classList.add('on'); c.innerHTML = ic('check'); });
  const cs = celeSnap([id]);
  const j = await api('POST', `/api/tasks/${id}/complete`, t.repeat && t.due ? {expect_due: t.due} : undefined);
  wpCloseLocal([id]);
  await load();
  render();
  if (!j.skipped) celeCheck(cs);
  if (j.skipped) toast(tr('Already checked off (other device), not advanced twice'));
  // 2.25.0 (UX-40): the message names the task ("“Take out the bins” completed · Undo")
  else offerUndo(j.next_due ? tr('{0}: next occurrence {1}', n, dayLabel(j.next_due)) : tr('{0} completed|task', n), histDone(tr('Completed {0}', n), [id], snaps, j));
}
async function wontDo(id) {
  const snaps = withKids(id), t = taskById(id);
  const j = await api('POST', `/api/tasks/${id}/complete`, {status: -1});
  await load(); render();
  offerUndo(tr("Won't do: {0}", qn((t?.title || '').slice(0, 40))), histDone(tr("Won't do: {0}", qn((t?.title || '').slice(0, 40))), [id], snaps, j, -1));
}
const canDelete = t => !!t && canEditList(t.list_id);  // 1.10.0: participants complete or discard, they never delete
async function deleteTask(id) {
  const t = taskById(id);
  if (t && !canDelete(t)) { roToast(); return; }
  const snaps = withKids(id);
  const r = await api('DELETE', '/api/tasks/' + id);
  if (S.sel === id) closeDetail();
  await load(); render();
  offerUndo(tr('“{0}” deleted', t ? t.title.slice(0, 30) : ''), histTrash(tr('Deleted {0}', qn((t?.title || '').slice(0, 40))), [id], snaps, r));
}
async function createTask(body) {
  const lid = body.list_id || (body.parent_id && taskById(body.parent_id)?.list_id), lt = listTags(lid);
  if (body.tags?.length && lt.length && !body.ltags) {  // 2.0.0: a #name of one of the list's tags is that list tag
    const m = g => lt.find(x => x.name.toLowerCase() === String(g).toLowerCase());
    body = {...body, ltags: body.tags.filter(m).map(g => m(g).name), tags: body.tags.filter(g => !m(g))};
  }
  const t = await api('POST', '/api/tasks', body);
  putTask(t); render();
  histCreate(t.parent_id ? tr('Subtask {0} added', qn(String(t.title).slice(0, 40))) : tr('Created {0}', qn(String(t.title).slice(0, 40))), t);
  requestAnimationFrame(() => { const r = $(`#view .trow[data-id="${t.id}"]`); if (r) { r.classList.add('flash'); r.scrollIntoView({block: 'nearest'}); } });
  return t;
}
