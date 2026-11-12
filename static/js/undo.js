/* Kalmido web client: Undo / redo history.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ undo / redo (D4)
// 2.905.0 (#5255, undo across devices stage 7): the steps live on the server, per person and across devices (the step groups
// of kalmido/core/undogroups.py, the list "Recent steps" of undolist.js). This file only holds the buttons (← / →), the
// keyboard (Ctrl/Cmd+Z back, Ctrl/Cmd+Shift+Z or Ctrl+Y forward), the toasts' "Undo" and the short list of this window's
// own steps: an entry (histAdd) is a label plus the group(s) the server recorded for it (gids: the header X-Kalmido-Undo-Gid
// of the write's answer, core.js rawFetch0 -> histUgid) or the outbox entries still on their way (qs); no copies, no
// functions of their own. Undo takes back the person's newest step (ul: the server's newest group, any device) with POST
// /api/undo/to/<id>; the toast's "Undo" exactly its own entry; redo POST /api/undo/<id>/redo. A change still waiting in the
// outbox is taken out of the queue (never sent); the server checks rights, conflicts and barriers and names what stayed.
// Areas whose writes record no server step yet keep their own undo / redo functions in the entry (label "only this device"
// in the list) until their area records steps (#5255: named in the result, a task for the rest).
const UNDO_FIELDS = ['list_id', 'section_id', 'parent_id', 'due', 'due_time', 'start', 'duration', 'reminders', 'repeat', 'repeat_from', 'priority', 'pinned', 'assignee_id', 'ttype', 'deadline', 'nag', 'assignee_group_id', 'plan_start', 'ms', 'milestone_id', 'locked'];  // 2.18.0: ms, milestone_id (#430)  // 2.11.0: plan_start  // 2.10.0: assignee_group_id  // 2.4.0: ttype (#340), 2.7.0: deadline, nag
UNDO_FIELDS.push('remind_at');  // 2.111.0 C (#2057): the fixed-time reminder
const HIST_FIELDS = [...UNDO_FIELDS, 'title', 'content', 'url', 'tags', 'fields'];
const HIST_MAX = 100, HIST_MENU = 100;  // 2.773.0 (#5250, #5242): 100 steps (was 30), the → menu lists them all (was 10) and scrolls
// fresh: the step groups of answers no entry took yet (histUgid); gtok: the bundling token of histGroup (X-Kalmido-Undo-Group)
const HIST = {undo: [], redo: [], busy: false, group: null, gToast: null, toastE: null, sess: 0, ids: {}, secmap: new Map(), fresh: [], gtok: ''};
const HIST_FRESH_MS = 8000;  // 2.905.0 (#5255): an answer's group older than this is no longer taken by a new entry
const snapTask = t => t ? JSON.parse(JSON.stringify(t)) : null;
const withKids = id => { const out = [], walk = x => { for (const k of children(x)) { out.push(snapTask(k)); walk(k.id); } }; out.push(snapTask(taskById(id))); walk(id); return out.filter(Boolean); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const rid = id => (+id < 0 && HIST.ids[id]) || +id;  // a task created offline: its real id once the outbox was sent
const secId = sid => { let s = sid; for (let i = 0; i < 50 && s && HIST.secmap.has(s); i++) s = HIST.secmap.get(s); return s; };  // re-created sections
const cancellable = e => { const i = OUT.q.indexOf(e); return i >= 0 && !e.sending && !(OUT.flushing && i === 0); };  // 2.126.0 D (#1989): sending = on its way (any tab)
const histPending = e => !!e && (e.parts ? e.parts.some(histPending) : (e.qs || []).some(q => !q.done && OUT.q.includes(q)));
const nv = v => v === '' || v === undefined ? null : v;
const qn = s => tr('“{0}”', s);  // a name in quotes, as the language writes them
// field changes: reverse of what actually changed (the label and whether a change happened at all; the server keeps the step)
function reverseOf(before, after, fields = UNDO_FIELDS) {
  const back = {}, prev = {};
  for (const k of fields) {
    if (k === 'fields') {
      const bf = before.fields || {}, af = after.fields || {}, fb = {}, fp = {};
      for (const f of new Set([...Object.keys(bf), ...Object.keys(af)])) if (nv(bf[f]) !== nv(af[f]) && fieldById(+f)?.type !== 'formula') { fb[f] = nv(bf[f]); fp[f] = nv(af[f]); }  // 2.43.0 (#1328): formulas follow their fields
      if (Object.keys(fb).length) { back.fields = fb; prev.fields = fp; }
      continue;
    }
    if (!(k in before) && !(k in after)) continue;
    if (k === 'content' && !(k in before && k in after)) continue;  // 2.280.0 F (#3108): a long note not loaded on one side (start state without it) is no change
    const arr = k === 'tags' || k === 'ltags';  // 2.26.0 (#936): list tags too (the multi panel adds / removes them)
    const a = arr ? [...(before[k] || [])].sort().join('\u0001') : nv(before[k]), b = arr ? [...(after[k] || [])].sort().join('\u0001') : nv(after[k]);
    if (a !== b) { back[k] = arr ? [...(before[k] || [])] : nv(before[k]); prev[k] = arr ? [...(after[k] || [])] : nv(after[k]); }
  }
  return Object.keys(back).length ? {...back, _prev: prev} : null;
}
// ---- the server's step groups
// core.js rawFetch0: a write's answer named the group its step went into (X-Kalmido-Undo-Gid); the next entry takes it
function histUgid(gid, url) {
  if (!(gid > 0)) return;
  HIST.fresh.push({gid, at: Date.now(), sett: /^\/api\/settings(\/|\?|$)/.test(String(url || ''))});  // 2.997.0 (#5697 #5699 #5703 #5710): sett, see histFresh
  if (HIST.fresh.length > 50) HIST.fresh.shift();
}
// 2.997.0 (#5697, #5699, #5703, #5710): the fresh groups an entry without a group of its own takes. The app saves settings by
// itself (the colour scheme of a new device, the arrangement of a view after drawing it) and the server records them as steps
// (accounts/setundo.py); such a group only goes to an entry of a setting (sett), never to the next step of another area: that
// entry took the setting's group, its own undo / redo no longer ran and Undo put the setting back instead (a receipt suggestion
// stayed accepted, a closed month closed, the ticks "checked" stayed)
const histFresh = (e, now = Date.now()) => HIST.fresh.filter(f => now - f.at < HIST_FRESH_MS && (!f.sett || e?.sett)).map(f => f.gid);
// the groups of an entry: its own, the ones of its outbox entries' answers, its parts'
function histGids(e) {
  if (!e) return [];
  const g = e.parts ? e.parts.flatMap(histGids) : [...(e.gids || []), ...(e.qs || []).map(q => q.res?._ugid)];
  return [...new Set(g.filter(x => x > 0))];
}
// an entry the server keeps (or will: a change still waiting in the outbox); else it is this device's own (local undo / redo)
const histSrv = e => !!e && (histGids(e).length > 0 || (e.parts ? e.parts.some(histSrv) : !!(e.qs || []).length));
// ---- building steps
// e: {label, res?, ids?, lids?, area?, post?(dir), undo?/redo? (only areas without server steps), ...}; snaps / after / pairs
// are not kept (no copies in the browser, #5255)
function histAdd(e) {
  e.lids = [...new Set([...(e.lids || []), ...(e.snaps || []).map(s => s?.list_id)].filter(Boolean))];
  if (e.q === undefined) e.q = e.res?._q || null;
  e.qs = e.qs || (e.q ? [e.q] : []);
  // only while its change still waits in the outbox: the tasks as they were, to show them again when it is taken out
  // (offline); gone once it was sent (histFree)
  e.local = e.qs.some(q => !q.done) && e.snaps?.length ? e.snaps : null;
  e.snaps = []; e.after = [];
  histFree();
  const now = Date.now(), own = e.res?._ugid || +(e.res?.undo_group || 0);  // 2.905.0 (#5255): the header's group, or the answer's own field (#5476 areas)
  e.gids = [...(e.gids || []), ...(own ? [own] : [])];
  if (!e.parts && !e.qs.length && !own && !e.gids.length) e.gids.push(...histFresh(e, now));  // 2.997.0 (#5697 ...): histFresh
  HIST.fresh = [];
  if (!e.at) { e.at = now; e.area = e.area || (e.sett ? 'self' : S.route?.mod || 'tasks'); }
  if (!e.parts && !e.gids.length && !e.qs.length && !e.undo) return e;  // nothing to take back (a change that joined one still waiting in the outbox: that entry has it)  // 2.773.0 (#5242): time and area for the list "Recent steps" (undolist.js)
  if (HIST.group) { HIST.group.push(e); return e; }
  HIST.undo.push(e);
  if (HIST.undo.length > HIST_MAX) HIST.undo.shift();
  HIST.redo = [];
  if (HIST.toastE && HIST.toastE !== e) { HIST.toastE = null; $('#toast')?.classList.add('hidden'); }  // the old toast would undo the wrong step
  renderHist();
  return e;
}
// 2.905.0 (#5255): an entry recorded before its write answered (optimistic, dialogs.js listPatch) takes the group of that
// answer afterwards; without it the group stayed in HIST.fresh (the next entry took it) and the entry went back on its own,
// as a new server step that Ctrl+Z then took back (the change came again)
function histOwn(e, gid) {
  if (!e || !(gid > 0)) return;
  e.gids = [...new Set([...(e.gids || []), gid])];
  HIST.fresh = HIST.fresh.filter(f => f.gid !== gid);
  renderHist();
}
// the waiting copies of entries whose change reached the server go (histAdd keeps them only while it waits)
function histFree() { for (const x of [...HIST.undo, ...HIST.redo]) if (x.local && !histPending(x)) x.local = null; }
// the server took these groups back (undo) or forward (redo) - also from the list "Recent steps": this window's entries
// made only of them change sides
function histMark(ids, dir) {
  if (!ids?.length) return;
  const from = dir === 'undo' ? 'undo' : 'redo', to = dir === 'undo' ? 'redo' : 'undo';
  for (const x of [...HIST[from]]) { const g = histGids(x); if (g.length && g.every(id => ids.includes(id))) { HIST[from] = HIST[from].filter(y => y !== x); HIST[to].push(x); } }
  renderHist();
}
// several recorded steps of one user action (e.g. a drop that makes a subtask standalone and moves it) become one; its
// writes carry one token (X-Kalmido-Undo-Group), so the server bundles them into one group too
async function histGroup(fn, label) {
  if (HIST.group) return fn();
  const g = HIST.group = [];
  HIST.gToast = null;
  HIST.gtok = [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
  try { return await fn(); } finally {
    HIST.group = null; HIST.gtok = '';
    const msg = HIST.gToast; HIST.gToast = null;
    const e = g.length === 1 ? g[0] : g.length ? {label: label || g[g.length - 1].label, parts: g, lids: g.flatMap(x => x.lids), at: g[0].at, area: g[0].area} : null;
    if (e) { e.group = true; histAdd(e); if (msg) histToast(msg, e); }
  }
}
// the toast with "Undo" for a step: takes back exactly that entry
function histToast(msg, e, ms = 6000) {  // 2.58.0 (#1810): ms = a longer toast for a big step
  if (!e) { toast(msg); return; }
  if (HIST.group && HIST.group.includes(e)) { HIST.gToast = msg; return; }
  toast(msg, async () => { await histIdle(); if (HIST.undo.includes(e)) histStep('undo', 1, [e]); }, ms);
  HIST.toastE = e;
}
// 2.489.0 (#4013): an Undo pressed while an earlier step still finishes (its reload, its message) waits for it instead of being
// dropped by histStep's busy guard (a quick delete right after an undo under load: the delete stayed)
async function histIdle() { while (HIST.busy) await sleep(50); }
// task steps: the label and the changed fields only (histText joins typing), the server keeps the step
const histSlim = ([b, a, f]) => {
  const keys = Object.keys(reverseOf(b, a, f || HIST_FIELDS) || {}).filter(k => k !== '_prev');
  const pick = x => ({id: x.id, title: x.title, list_id: x.list_id, ...Object.fromEntries(keys.map(k => [k, x[k]]))});
  return [pick(b), pick(a), f];
};
// task field steps: [before, after, fields?] per task (null when nothing changed)
function histFields(label, pairs, o = {}) {
  pairs = pairs.filter(p => p[0] && p[1] && reverseOf(p[0], p[1], p[2] || o.fields || HIST_FIELDS));
  if (!pairs.length) return null;
  return histAdd({label, pairs: pairs.map(histSlim), res: o.res, lids: pairs.flatMap(p => [p[0].list_id, p[1].list_id]), text: o.text, sess: o.sess,
    ...(o.qs?.length ? {qs: o.qs} : {}), ...(o.gids?.length ? {gids: o.gids} : {})});
}
// 2.537.0 (#4568): the dependent tasks the server moved along with a step recorded already (its answer came after the step:
// attachments.js shiftLate) are in the same server group; label = a part for its name ("2 dependent tasks moved")
function histExtend(e, pairs, label) {
  pairs = (pairs || []).filter(p => p[0] && p[1] && reverseOf(p[0], p[1], p[2] || HIST_FIELDS) && !e?.pairs?.some(q => q[0].id === p[0].id));
  if (!e?.pairs || !pairs.length) return false;
  e.pairs.push(...pairs.map(histSlim));
  if (label && !e.label.includes(label)) e.label = [e.label, label].filter(Boolean).join(' · ');
  renderHist();
  return true;
}
// completion / won't do, reopened, to the trash, created: the server's step of the request (res = its answer)
function histDone(label, ids, snaps, res) { return histAdd({label, snaps, ids, res}); }
function histReopen(label, id, snaps, res) { return histAdd({label, snaps, ids: [id], res}); }
function histTrash(label, ids, snaps, res) { return histAdd({label, snaps, ids, res}); }
function histCreate(label, t, extra = {}) { return histAdd({label, ids: [t.id], res: t, lids: [t.list_id], ...extra}); }
// ---- going back and forth
const histFieldName = f => f.startsWith('field:') ? fieldById(+f.slice(6))?.name || tr('Custom field') : FIELD_NAMES[f] ? tr(FIELD_NAMES[f]) : {status: tr('Status'), changed: tr('changed by someone else'), order: tr('Order'), name: tr('Name'), section: tr('Section'), folder: tr('Folder')}[f] || f;
const histTitle = (id, t) => qn(String(t || S.tasks.get(rid(id))?.title || '').slice(0, 30));
// a task batch (the undo / redo functions of areas without server steps, popovers.js, projects.js, related.js)
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
// a change taken out of the outbox before it was sent: the page shows the state before it (online: the reload does it)
function histUnq(q, local) {
  for (const t of local || []) if (t?.id) S.tasks.set(rid(t.id), {...(S.tasks.get(rid(t.id)) || {}), ...snapTask(t), id: rid(t.id)});
  const m = String(q.url || '').match(/^\/api\/tasks\/(-?\d+)$/);
  if (q.method === 'POST' && q.tmp) S.tasks.delete(q.tmp);
  else if (m && q.method === 'PATCH' && q.body?._prev && S.tasks.has(+m[1])) S.tasks.set(+m[1], {...S.tasks.get(+m[1]), ...q.body._prev});
}
// the outbox entries of a step: on their way -> wait for the answer; not sent yet (undo) -> out of the queue (kept for redo)
async function histQ(e, dir) {
  let cut = 0;
  for (const q of e.qs || []) {
    for (let n = 0; n < 400 && !q.done && !cancellable(q); n++) await sleep(150);
    if (dir === 'undo' && !q.done && cancellable(q)) {
      outSave(() => { OUT.q = OUT.q.filter(x => x !== q); });  // 2.126.0 D (#1989): the shared queue
      histUnq(q, e.local); (e.cut = e.cut || []).push(q); cut++;
    }
  }
  e.qs = (e.qs || []).filter(q => !(e.cut || []).includes(q));
  if (cut) renderTop();
  return cut;
}
// the server's answer of an undo / redo -> {skipped, note, none, undone: [gids]}
// the server names the fields that stayed by their keys ("field:3", "priority"): the names this person reads
const histReason = r => String(r).replace(/: ([a-z_:0-9]+(?:, [a-z_:0-9]+)*)$/, (m, l) => ': ' + l.split(', ').map(histFieldName).join(', '));
function histSrvRes(a, dir) {
  const stayed = (a?.stayed || []).map(x => x.reason).filter(Boolean).map(histReason);
  const moved = dir === 'undo' ? (a?.undone || []).length + (a?.partial || []).length : +(a?.redone || 0);
  const st = stayed.slice(0, 4).join('; ') + (stayed.length > 4 ? ' …' : '');
  const note = [a?.stopped ? tr('Stopped before a step that cannot be undone: {0}', a.stopped.label || '') : '',
    stayed.length ? (moved ? tr('Stayed as it is: {0}', st) : st) : ''].filter(Boolean).join(' ');  // nothing went: the server's reason alone
  return {skipped: [], note, none: !moved && !!(stayed.length || a?.stopped), undone: [...(a?.undone || []), ...(a?.partial || [])]};
}
// one entry back or forth: its outbox entries first, then its server groups, then (areas without server steps) its own functions
async function histDo(e, dir) {
  const out = {skipped: [], queued: false, note: '', none: false, srv: false, undone: []};
  const parts = e.parts ? (dir === 'undo' ? [...e.parts].reverse() : e.parts) : [e];
  let cut = 0;
  for (const p of parts) cut += await histQ(p, dir);
  if (dir === 'redo') for (const p of parts) for (const q of p.cut || []) { const r = await api(q.method, q.url, q.body); cut++; if (r?._q) p.qs = [...(p.qs || []), r._q]; out.queued = out.queued || !!r?._q; }  // the change taken out goes again
  for (const p of parts) if (dir === 'redo') p.cut = [];
  const gids = histGids(e).sort((a, b) => a - b);
  if (gids.length) {
    out.srv = true;
    if (dir === 'undo') Object.assign(out, histSrvRes(await api('POST', `/api/undo/to/${gids[0]}`), dir), {srv: true});
    else {
      let n = 0;
      for (const g of gids) { try { const r = histSrvRes(await api('POST', `/api/undo/${g}/redo`), dir); if (!r.none) n++; out.note = out.note || r.note; } catch (x) { if (x?.status !== 409) throw x; } }
      out.none = !n && !cut;
    }
  }
  for (const p of parts) {
    if (histSrv(p) || (p.cut || []).length || !p[dir]) continue;  // the server (or the outbox) had it
    const r = await p[dir](p) || {};
    HIST.fresh = [];  // 2.905.0 (#5255): a group its own write recorded belongs to no new entry
    out.skipped.push(...(r.skipped || [])); out.note = out.note || r.note || ''; out.none = out.none || !!r.none; out.queued = out.queued || !!r.q;  // 2.560.0 (#4667): note = a sentence instead of "Undone: …"
  }
  if (!gids.length && !cut && !parts.some(p => p[dir] && !histSrv(p))) out.none = true;  // nothing the server or this device could take back
  return out;
}
// the person's newest step: this window's newest entry, unless the server has a newer group (another device, a write
// without an entry here) -> an entry or {label, gids, row} of that group
async function histNext() {
  const top = HIST.undo[HIST.undo.length - 1];
  if (top && histPending(top)) return top;  // just made, its change still on its way: it is the newest
  let g = null;
  if (histListable()) { try { g = ((await rawFetch('GET', '/api/undo?limit=20')).items || []).find(x => x.state !== 'undone') || null; } catch { g = null; } }
  if (!g) return top || null;
  const tg = histGids(top);
  if (top && (tg.length ? Math.max(...tg) >= g.id : (top.at || 0) >= (Date.parse(g.at) || 0))) return top;
  return HIST.undo.find(x => histGids(x).includes(g.id)) || {label: g.label || tr('Change'), gids: [g.id], row: g, lids: [], at: Date.parse(g.at) || 0};
}
const HIST_OFF = ['barrier', 'toobig', 'noaccess'];  // the server's groups that cannot go back (and hold the older ones)
// 2.979.0 (#5667): the areas registered with histReloader (core.js) fetch their data again
async function histReloadAreas() {
  await Promise.all([...HIST_RELOAD].map(async ([name, fn]) => { try { await fn(); } catch (err) { console.warn('history reload', name, err); } }));
}
// after an undo / redo: the views show the state again (tasks, an open office document, an open table, the registered areas)
async function histRedraw(srv) {
  if (OUT.online && !OUT.q.length) await load().catch(() => {});
  render();
  if (S.sel) { if (taskById(S.sel)) renderDetail(); else closeDetail(); }
  if (!srv) return;
  if (typeof OFD !== 'undefined' && typeof ofdLoadDoc === 'function' && OFD.doc?.id) { OFD.list = null; await ofdLoadDoc(OFD.doc.id, true).catch(() => {}); }  // lazy-ok: an open office document
  else if (typeof ofcReload === 'function' && S.route?.mod === 'office') ofcReload();  // lazy-ok
  if (typeof SHV !== 'undefined' && SHV.sh && typeof shvReload === 'function') await shvReload().catch(() => {});  // lazy-ok: an open table
  if (typeof ab_relist === 'function' && ['ablage', 'docs'].includes(S.route?.mod)) ab_relist();  // lazy-ok: 2.959.0 (#4805): the file store / documents list (a node back from the trash)
  await histReloadAreas();  // 2.979.0 (#5667)
}
// n steps back (undo) or forward (redo), one after the other
// 2.773.0 (#5250): only = these entries (newest first) instead of the newest n (the toast's own entry, the list "Recent
// steps"); -> {done, stop} (how many went, whether it stopped before the end)
async function histStep(dir, n = 1, only = null) {
  if (HIST.busy) return {done: 0, stop: true};
  if (only) n = only.length;
  HIST.busy = true; renderHist();
  const done = [], skipped = [];
  let queued = false, stop = false, dropped = null, note = '', srv = false;
  const other = dir === 'undo' ? 'redo' : 'undo';
  const out = e => { HIST.undo = HIST.undo.filter(x => x !== e); HIST.redo = HIST.redo.filter(x => x !== e); };
  try {
    await flushSaves();
    for (let i = 0; i < n && !stop; i++) {
      const e = only ? only[i] : dir === 'undo' ? await histNext() : HIST.redo[HIST.redo.length - 1];
      if (!e || (only && !HIST[dir].includes(e))) break;
      if (e.row && HIST_OFF.includes(e.row.state)) { toast(e.row.state === 'noaccess' ? tr('You may not change it any more, so it cannot be undone') : tr('Stopped before a step that cannot be undone: {0}', e.label)); stop = true; break; }
      if (e.lids.some(l => listById(l) && !canAddTo(l))) {  // the list became view-only in the meantime (the server checks again)
        out(e); stop = true;
        toast(dir === 'undo' ? tr('Read-only: “{0}” can no longer be undone', e.label) : tr('Read-only: “{0}” can no longer be redone', e.label));
        break;
      }
      let r;
      try { r = await histDo(e, dir); } catch (x) {
        if (!(x instanceof Offline) && x.message !== 'auth') { out(e); dropped = e; }  // gone or no rights: api() said why
        stop = true; break;
      }
      out(e);
      if (dir === 'undo') histMark(r.undone, 'undo');  // newer groups went with it (the server's order)
      if (r.none && !r.skipped.length && !r.note) r.skipped.push(e.label);
      if (r.none) dropped = e;  // nothing could be applied (changed elsewhere): out of the history
      else if (!e.row) HIST[other].push(e);
      else if (dir === 'undo') HIST.redo.push(e);
      done.push(e); skipped.push(...r.skipped); queued = queued || r.queued; note = note || r.note || ''; srv = srv || r.srv;
      if (r.none) stop = true;
    }
  } finally {
    try {  // the page may be gone meanwhile (closed tab, tests)
      if (done.length || dropped) {
        await histRedraw(srv);
        for (const x of done) { try { x.post?.(dir); } catch (err) { console.warn('history post', err); } }
      }
      if (done.length && !(HIST.toastE && !done.includes(HIST.toastE))) {  // 2.489.0 (#4013): a newer step's Undo message stays
        if (skipped.length) toast((dir === 'undo' ? tr('Changed elsewhere, not undone: {0}', skipped.slice(0, 4).join(', ')) : tr('Changed elsewhere, not redone: {0}', skipped.slice(0, 4).join(', '))) + (skipped.length > 4 ? ' …' : ''));
        else {
          const what = done.length > 1 ? (dir === 'undo' ? trn('{0} step undone', '{0} steps undone', done.length) : trn('{0} step redone', '{0} steps redone', done.length))
            : dir === 'undo' ? tr('Undone: {0}', done[0].label) : tr('Redone: {0}', done[0].label);
          toast(note || (queued && !OUT.online ? what + ' · ' + tr('sent as soon as you are online') : what), null, note ? 10000 : undefined);  // 2.560.0 (#4667): e.g. restored without its client; 2.951.0 (#5638): the hint only offline (online the outbox sends it at once)
        }
      }
    } catch (x) { console.warn('history', x); }
    HIST.busy = false;
    try { renderHist(); } catch { /* page gone */ }
  }
  return {done: done.length, stop};  // 2.773.0 (#5250)
}
// ---- the ← / → buttons (top bar), their tooltips and the history menu
function histBtn(dir) {
  const e = HIST[dir][HIST[dir].length - 1], p = histPending(e);
  const lab = e ? (dir === 'undo' ? tr('Undo: {0}', e.label) : tr('Redo: {0}', e.label)) : dir === 'undo' ? tr('Nothing to undo') : tr('Nothing to redo');
  // 2.773.0 (#5250): list = nothing to undo here, the button opens the list "Recent steps" (the person's steps of every device)
  const list = dir === 'undo' && !e && histListable();
  return {lab, tip: lab + (e ? ` (${kbText(dir === 'undo' ? 'Mod+Z' : 'Mod+Shift+Z')})` : '') + (p ? ' · ' + tr('waiting for the connection') : ''), off: !e || HIST.busy, p, list};
}
const histListable = () => !!S.me && S.me.kind !== 'agent' && !S.me.kid;  // 2.773.0 (#5250): a person has the list "Recent steps"
function histBtns() {
  return `<div class="hist tf" role="group" aria-label="${esc(tr('History'))}">${['undo', 'redo'].map(dir => { const b = histBtn(dir), lab = b.list ? tr('Recent steps') : b.lab; return `<button type="button" class="iconbtn hbtn${b.p ? ' pend' : ''}" data-act="hist-${dir}" aria-label="${esc(lab)}" title="${esc(b.list ? lab : b.tip)}"${b.off && !b.list ? ' disabled' : ''}>${ic(dir === 'undo' ? 'undo' : 'redo')}</button>`; }).join('')}</div>`;
}
function renderHist() {  // in place: keeps the keyboard focus on the button
  for (const dir of ['undo', 'redo']) {
    const el = $(`#top [data-act="hist-${dir}"]`); if (!el) continue;
    const b = histBtn(dir);
    const lab = b.list ? tr('Recent steps') : b.lab;  // 2.773.0 (#5250)
    el.disabled = b.off && !b.list; el.title = b.list ? lab : b.tip; el.setAttribute('aria-label', lab); el.classList.toggle('pend', b.p);
  }
}
function histMenu(anchor, dir) {
  if (dir === 'undo' && S.me?.kind !== 'agent') { $('#toast')?.classList.add('hidden'); ul_open(anchor); return; }  // 2.773.0 (#5250): the list "Recent steps" (undolist.js, loaded on demand)
  const list = HIST[dir].slice(-HIST_MENU).reverse();
  if (!list.length || HIST.busy) return;
  $('#toast')?.classList.add('hidden');
  menu(anchor, list.map((e, i) => ({label: e.label, sub: histWhen(e), icon: dir === 'undo' ? 'undo' : 'redo', cls: 'hitem' + (histPending(e) ? ' pend' : ''), fn: () => histStep(dir, i + 1)})));
  const p = $('#pop');
  if (p) {
    p.querySelector('.menu-list')?.insertAdjacentHTML('afterbegin', `<div class="hhead">${esc(dir === 'undo' ? tr('Undo up to here') : tr('Redo up to here'))}</div>`);
    p.querySelector('.menu-list')?.setAttribute('aria-label', dir === 'undo' ? tr('Undo history') : tr('Redo history'));
  }
}
// 2.773.0 (#5242): "Office · 20:58" under a step (its area as the app names it, the time in the reader's format)
function histWhen(e) {
  if (!e?.at) return '';
  const t = new Date(e.at).toLocaleTimeString(LOCALE(), {hour: '2-digit', minute: '2-digit'});
  return [histAreaName(e.area), t].filter(Boolean).join(' · ');
}
// the areas of a step: the app's views (S.route.mod) and the server's areas (core/db.py LV_AREAS, undo_groups.area)
const HIST_AREAS = {tasks: N_('Tasks'), home: N_('Tasks'), comments: N_('Comments'), office: N_('Office'), clients: N_('Office'), calendar: N_('Calendar'), cal: N_('Calendar'),
  sheets: N_('Tables'), wiki: N_('Knowledge|area'), budget: N_('Budget'), team: N_('Team'), time: N_('Time tracking'), contacts: N_('Contacts'), docs: N_('Documents'),
  ablage: N_('File store'), notes: N_('Notes'), family: N_('Family'), news: N_('News'), agentchat: N_('Agent chat'), agents: N_('Agents'), self: N_('Settings'), other: N_('Other')};
const histAreaName = a => a ? tr(HIST_AREAS[a] || N_('Other')) : '';
// 2.773.0 (#5250): the name of this browser in the list "Recent steps" of the person's other devices (header
// X-Kalmido-Device-Name of a write, core.js rawFetch0; kalmido/core/undogroups.py ug_device): browser + system + a short
// mark of its own, kept in localStorage (ASCII only: a header value)
function histDevice() {
  let v = LS.get('undoDev', '');
  if (!v) {
    const ua = navigator.userAgent || '';
    const br = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
    const os = /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac OS X/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : '';
    v = `${br}${os ? ' on ' + os : ''} (${Math.random().toString(36).slice(2, 6)})`;
    LS.set('undoDev', v);
  }
  return v;
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
  if (ch.length === 1 && has('locked')) return a.locked ? tr('Locked {0}', n) : tr('Unlocked {0}', n);  // 2.36.0 (#1118)
  if (has('list_id')) return tr('Moved {0} to {1}', n, lname(listById(a.list_id)) || '?');
  if (has('parent_id')) return a.parent_id ? tr('{0} is now a subtask', n) : tr('{0} is now a main task', n);
  if (ch.length === 1 && has('title')) return tr('Renamed {0}', n);
  if (ch.length === 1 && has('content')) return tr('Description of {0}', n);
  if (ch.length === 1 && has('priority')) return tr('Priority of {0}: {1}', n, tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High'), '', N_('Urgent')][+a.priority || 0] || N_('None')));
  if (ch.length === 1 && has('tags')) return tr('Tags of {0}', n);
  if (ch.length === 1 && has('assignee_id')) return a.assignee_id ? tr('{0} assigned to {1}', n, personName(a.list_id, a.assignee_id) || '?') : tr('{0} unassigned', n);
  if (ch.length === 1 && has('fields')) { const f = Object.keys(reverseOf(b, a, ['fields']).fields); return f.length === 1 ? tr('{0} of {1}', fieldById(+f[0])?.name || tr('Custom field'), n) : tr('Custom fields of {0}', n); }
  if (ch.length === 1 && has('pinned')) return a.pinned ? tr('Pinned {0}', n) : tr('Unpinned {0}', n);
  if (ch.length === 1 && has('url')) return tr('Link of {0}', n);
  if (ch.length === 1 && has('section_id')) return tr('Moved {0} to section {1}', n, secName(a.section_id));
  if (has('plan_start') && !has('due')) return a.plan_start ? tr('Planned {0}', n) : tr('Unplanned {0}', n);  // 2.11.0
  if (has('due') || has('start') || has('due_time')) return a.due ? tr('Date of {0}: {1}', n, dayLabel(a.due)) : tr('Date of {0} removed', n);
  if (has('repeat') || has('repeat_from')) return tr('Repeat of {0}', n);
  if (has('reminders') || has('remind_at')) return tr('Reminder of {0}', n);  // 2.111.0 C (#2057): + remind_at
  return tr('Edited {0}', n);
}
// 2.273.0 B (#3042): what a move ended (people coming along, further projects, subtasks left behind, ...); the server keeps
// it, so Undo or moving the task back within a day brings it back
function tmm_msg(msg, r) {
  const x = r?.move_ended; if (!x) return msg;
  const p = [x.people && trn('{0} person coming along', '{0} people coming along', x.people), x.links && trn('{0} further project', '{0} further projects', x.links),
    x.subtasks && trn('{0} subtask stays in its project', '{0} subtasks stay in their projects', x.subtasks), x.assignee && tr('Assignee'), x.group && tr('Group'),
    x.milestone && tr('Milestone'), x.sprint && tr('Sprint'), x.ltags && trn('{0} project tag', '{0} project tags', x.ltags),
    x.client && tr('Client'), x.visibility && tr('Everyone in the organisation'), x.assignees && trn('{0} assignment of a reader', '{0} assignments of readers', x.assignees),
    x.tclients && trn('{0} client of a client report', '{0} clients of client reports', x.tclients),
    x.watchers && trn('{0} watcher', '{0} watchers', x.watchers), x.delegate && tr('Delegation to an agent')].filter(Boolean);  // 2.530.0 B (#4316)  // a list's workspace (dialogs.js); 2.401.0 (#2924): + tclients
  return p.length ? `${msg || tr('Moved')} · ${tr('Not carried over: {0}. Undo brings it back.', p.join(', '))}` : msg;
}
// the few older callers: a toast with "Undo" for a step built above
function offerUndo(msg, e) { histToast(msg, e); }
async function patchUndoable(id, body, msg) {
  const before = snapTask(taskById(id));
  if (body?.list_id && typeof ln_moveHint === 'function') ln_moveHint(id, body.list_id);  // 2.48.0 (#1642): a locked note stays locked
  if (body?.list_id) msg = wsc_moveMsg(taskById(id)?.list_id, body.list_id, msg);  // 2.53.0 (#1474): Private -> organisation: who sees it now
  const t = await patchTask(id, body, true);
  msg = tmm_msg(msg, t);  // 2.273.0 B (#3042)
  if (t?.shifted?.length || t?.chain?.skipped?.length) { shiftUndo(before, t, msg); return t; }  // 2.67.0 B (#1865)
  const after = snapTask(S.tasks.get(id) || t);
  const e = before && after && histFields(histLabel(before, after), [[before, after]], {res: t});
  if (e) offerUndo(msg, e);
  else if (msg) toast(msg);
  if (before) shiftLate(before, e || null, msg, t);  // 2.537.0 (#4568): the outbox's answer may still move dependent tasks along
  return t;
}
// 2.542.0 (#4579): the open subtasks (all levels) a completion ticks off along (server cascade lifecycle.do_complete; a locked
// one stays open there); skip = ids ticked in the same step (a selection), not counted twice
const ckOpenKids = (id, skip) => { let n = 0; const walk = x => { for (const k of children(x)) { if (k.status === 0 && !k.locked && !skip?.has(k.id)) n++; walk(k.id); } }; walk(id); return n; };
// one question before ticking tasks with open subtasks (tick, swipe, x, selection, Start): true = go on
async function ckKidsAsk(ts) {
  const skip = new Set(ts.map(t => t.id)), has = ts.map(t => [t, ckOpenKids(t.id, skip)]).filter(([, n]) => n);
  if (!has.length) return true;
  const n = has.reduce((s, [, k]) => s + k, 0);
  if (has.every(([t]) => t.repeat && t.due)) {  // a recurring task moves on: its subtasks are open again at the next occurrence (04.11. 21:04)
    return askConfirm(trn('{0} open subtask left. It will be open again at the next occurrence; here it counts as not done. Complete anyway?',
      '{0} open subtasks left. They will be open again at the next occurrence; here they count as not done. Complete anyway?', n), '', {ok: tr('Complete anyway')});
  }
  return askConfirm(trn('{0} open subtask left. Complete it too?', '{0} open subtasks left. Complete them all?', n), '', {ok: tr('Complete all'), cancel: tr('Cancel')});
}
// 2.910.0 (#5444): a completion the server refused: the circle of the row is empty again (as lstStatusOpt puts a status back)
const chkBack = id => $$(`.trow[data-id="${id}"] .chk`).forEach(c => { c.classList.remove('on'); c.innerHTML = ''; if (c.hasAttribute('aria-checked')) c.setAttribute('aria-checked', 'false'); });
async function toggleTask(id) {
  const t = taskById(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  if (tlkDone(t)) return;  // 2.542.0 (#4609): locked: the hint with "Unlock" first (before the subtask question), the server refuses it too
  const pend = UI.pend.get(id);
  if (pend) {  // 2.49.0 (#1766): ticked again while the exit runs: cancel it and reopen
    pend.cancel(); UI.pend.delete(id);
    $$(`.trow[data-id="${id}"] .chk`).forEach(c => { c.classList.remove('on'); c.innerHTML = ''; });
    await pend.api;
    const r = await api('POST', `/api/tasks/${id}/reopen`); const {undo, ...rt} = r; putTask(rt);
    await load(); render();
    return;
  }
  const snaps = withKids(id), n = qn(toastClip(t.title));  // 2.218.0 B (#2801): the title is cut short, the verb stays
  if (t.status !== 0) {
    const fade = an_rowOut([id]);  // 2.46.1 (#1559): the row fades while the request runs; the redraw waits for it
    let r; try { r = await api('POST', `/api/tasks/${id}/reopen`); } catch (x) { an_rowsBack([id]); throw x; }
    await fade;
    const {undo, ...rt} = r; putTask(rt);
    if (S.extra) S.extra = S.extra.filter(x => x.id !== id);
    render();
    offerUndo(tr('Reopened {0}', n), histReopen(tr('Reopened {0}', n), id, snaps, r));
    return;
  }
  if (rvw_blocked(t)) { rvw_blockedAsk(t); return; }  // 2.60.0 C (#1512): waits for the review approval (the server says 409)
  if (t.blocked && dFor(t) && !await askConfirm(tr('“{0}” is still blocked by {1}. Complete it anyway?', t.title, blockedNames(t)), '', {ok: tr('Complete anyway')})) return;
  if (!await ckKidsAsk([t])) return;  // 2.542.0 (#4579)
  // optimistic: strike the row through, then sync
  $$(`.trow[data-id="${id}"] .chk`).forEach(c => { c.classList.add('on'); c.innerHTML = ic('check'); });
  const cs = celeSnap([id]);
  const anim = ui_doneStart(id, doneToggleView() && !showDone());  // 2.49.0 (#1766): line first, then the exit when completed tasks are hidden
  UI.pend.set(id, anim);
  const call = api('POST', `/api/tasks/${id}/complete`, t.repeat && t.due ? {expect_due: t.due, ...(/TIMES=/.test(t.repeat) ? {expect_time: t.due_time || ''} : {})} : undefined);  // 2.116.0 review F2: + the time of a several-times-a-day rule
  anim.api = call.catch(() => {});
  let j; try { j = await call; } catch (x) { anim.cancel(); UI.pend.delete(id); an_rowsBack([id]); chkBack(id); throw x; }  // 2.910.0 (#5444): + the tick goes back
  await anim.done; await ui_idle();
  if (anim.cancelled) return;  // ticked off again meanwhile: that call reopens
  UI.pend.delete(id);
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
  if (tlkDone(t)) return;  // 2.542.0 (#4609)
  const fade = an_rowOut([id]);  // 2.46.1 (#1559)
  let j; try { j = await api('POST', `/api/tasks/${id}/complete`, {status: -1}); } catch (x) { an_rowsBack([id]); throw x; }
  await fade; await load(); render();
  offerUndo(tr("Won’t do: {0}", qn(toastClip(t?.title))), histDone(tr("Won’t do: {0}", qn(toastClip(t?.title))), [id], snaps, j, -1));
}
const canDelete = t => !!t && canEditList(t.list_id);  // 1.10.0: participants complete or discard, they never delete
async function deleteTask(id) {
  const t = taskById(id);
  if (t && !canDelete(t)) { roToast(); return; }
  const snaps = withKids(id);
  const fade = an_rowOut([id]);  // 2.46.1 (#1559)
  let r; try { r = await api('DELETE', '/api/tasks/' + id); } catch (x) { an_rowsBack([id]); throw x; }
  await fade;
  if (S.sel === id) closeDetail();
  await load(); render();
  offerUndo(tr('“{0}” deleted', t ? t.title.slice(0, 30) : ''), histTrash(tr('Deleted {0}', qn((t?.title || '').slice(0, 40))), [id], snaps, r));
}
async function createTask(body) {
  const lid = body.list_id || (body.parent_id && taskById(body.parent_id)?.list_id), lt = [...listTags(lid), ...orgLabels(lid)];  // 2.609.0 (#3373): + the organisation's labels
  if (body.tags?.length && lt.length && !body.ltags) {  // 2.0.0: a #name of one of the list's tags is that list tag
    const m = g => lt.find(x => x.name.toLowerCase() === String(g).toLowerCase());
    body = {...body, ltags: body.tags.filter(m).map(g => m(g).name), tags: body.tags.filter(g => !m(g))};
  }
  if (!body.parent_id && lid && fieldsOf(lid).some(f => f.required && body.fields?.[f.id] == null)) {  // 2.609.0 (#3373): ask first
    const fv = await rqf_ask(lid, body); if (!fv) throw new Error(tr('Not created: a required field is empty'));
    body = {...body, fields: {...body.fields, ...fv}};
  }
  const t = await api('POST', '/api/tasks', body);
  putTask(t); render();
  histCreate(t.parent_id ? tr('Subtask {0} added', qn(String(t.title).slice(0, 40))) : tr('Created {0}', qn(String(t.title).slice(0, 40))), t);
  requestAnimationFrame(() => { const r = $(`#view .trow[data-id="${t.id}"]`); if (r) { r.classList.add('flash'); if (an_on()) r.classList.add('an-rowin'); r.scrollIntoView({block: 'nearest'}); } });
  return t;
}
