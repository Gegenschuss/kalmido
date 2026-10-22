/* Kalmido web client: the bell of one task (2.53.0 C, #1424) -- As the list / Muted / Urgent, per person.
   A button in the task header (tbl_btnHtml, detail.js) opens a menu; the list's owner / admins can mark the task urgent
   for people of the list ("Urgent for others…"). The state comes from GET /api/tasks/<id>/bell when the task opens
   (cached in S.tbl), every change is ONE undo step (POST .../bell/undo with the change's token).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const TBL_ICON = {list: 'bell', mute: 'belloff', urgent: 'bellring'};
const TBL_LABEL = {list: N_('As the project'), mute: N_('Muted'), urgent: N_('Urgent|bell')};
const tbl_cache = () => (S.tbl = S.tbl || {});
// the honest limit of "Urgent" (Android / ntfy vs. the iPhone web app)
const tbl_hint = () => tr('Urgent sends every change and comment of this task as a push at the highest priority. On Android (ntfy) it comes through. On an iPhone the web app cannot break through Focus or silent mode: there it is a prominent push, not an alarm.');

function tbl_untilTxt(m) {
  return m.until ? tr('until {0}', fmtDateLoc(m.until)) : tr('until completed');
}
const tbl_state = tid => tbl_cache()[tid] || null;
const TBL_LOADING = new Map();  // task id -> the running request
// the header button: only when the bell is not "As the list" (or for someone who cannot edit the task: their only way,
// the "…" menu is not there); the menu "…" of the task always has "Notifications for this task…" (tbl_menuItems).
// Not loaded yet / as the list: an empty placeholder that tbl_paint fills in.
function tbl_btnHtml(t, ck) {
  if (ck || !(t?.id > 0) || t.context || typeof collab !== 'function' || !collab()) return '';
  const j = tbl_state(t.id);
  if (S.tblLast !== t.id) { S.tblLast = t.id; tbl_load(t.id, true); }  // fresh each time a task opens (others may have changed it)
  else if (!j) tbl_load(t.id);
  const m = j?.mine || {level: 'list'}, lv = m.level || 'list';
  if (!j || (lv === 'list' && (typeof canEdit !== 'function' || canEdit(t)))) return `<i class="tbl-ph" data-tblph="${t.id}" hidden></i>`;
  const by = m.by_name && m.set_by !== S.me?.id ? m.by_name : '';
  const word = lv === 'urgent' ? (by ? tr('Urgent, set by {0}', by) : tr('Urgent|bell')) : tr(TBL_LABEL[lv]);
  const tip = tr('Notifications for this task') + ': ' + word + (lv === 'urgent' ? ' · ' + tbl_untilTxt(m) : '') + (lv === 'urgent' && m.active === false ? ' · ' + tr('not active') : '');
  return `<button type="button" class="iconbtn tbl-b lv-${lv}${lv !== 'list' ? ' on' : ''}${m.active === false && lv === 'urgent' ? ' off' : ''}" data-tblb="${t.id}" aria-haspopup="menu" title="${esc(tip)}" aria-label="${esc(tip)}">${ic(TBL_ICON[lv] || 'bell')}<span class="dpw">${esc(lv === 'urgent' ? tr('Urgent|bell') : tr(TBL_LABEL[lv]))}</span></button>`;
}
// the item of the task's menu "…" (popovers.js taskMenu)
const tbl_menuItems = (t, anchor) => t?.id > 0 && !t.context && typeof collab === 'function' && collab()
  ? [{label: tr('Notifications for this task…'), icon: TBL_ICON[tbl_state(t.id)?.mine?.level] || 'bell', fn: () => tbl_menu(anchor?.isConnected ? anchor : $('#detail .dtop') || document.body, t.id)}] : [];
function tbl_load(tid, force) {
  const C = tbl_cache();
  if (TBL_LOADING.has(tid)) return TBL_LOADING.get(tid);
  if (C[tid] && !force) return Promise.resolve(C[tid]);
  const p = rawFetch('GET', `/api/tasks/${tid}/bell`).then(j => { C[tid] = j; tbl_paint(tid); return j; }, () => C[tid] || null)
    .finally(() => TBL_LOADING.delete(tid));
  TBL_LOADING.set(tid, p);
  return p;
}
function tbl_paint(tid) {
  const t = typeof taskById === 'function' ? taskById(tid) : null;
  for (const b of $$(`[data-tblb="${tid}"],[data-tblph="${tid}"]`)) {
    if (!t) continue;
    const h = tbl_btnHtml(t, false); if (!h) continue;
    const w = document.createElement('div'); w.innerHTML = h;
    b.replaceWith(w.firstElementChild);
  }
}
async function tbl_req(method, url, body) {
  try { return await rawFetch(method, url, body); } catch (e) {
    toast(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message || tr('Error'));
    throw e;
  }
}
// one change = one undo step; redo repeats it (with a new token)
async function tbl_change(tid, body, label) {
  let j;
  try { j = await tbl_req('PUT', `/api/tasks/${tid}/bell`, body); } catch { return; }
  tbl_cache()[tid] = j; tbl_paint(tid);
  if (!j.act) return;
  let act = j.act;
  const e = histAdd({label, undo: async () => { const r = await tbl_req('POST', `/api/tasks/${tid}/bell/undo`, {act}); tbl_cache()[tid] = r; tbl_paint(tid); },
    redo: async () => { const r = await tbl_req('PUT', `/api/tasks/${tid}/bell`, body); act = r.act; tbl_cache()[tid] = r; tbl_paint(tid); }});
  offerUndo(label, e);
}
const tbl_set = (tid, level, until = null) => tbl_change(tid, level === 'urgent' ? {level, until} : {level},
  tr('Notifications for this task: {0}', level === 'urgent' ? tr('Urgent|bell') + ' · ' + (until ? tr('until {0}', fmtDateLoc(until)) : tr('until completed')) : tr(TBL_LABEL[level])));

async function tbl_menu(anchor, tid) {
  const j = await tbl_load(tid);
  if (!j) { toast(tr('Offline: only works again with a connection')); return; }
  const m = j.mine, lv = m.level, foreign = lv === 'urgent' && m.set_by && m.set_by !== S.me?.id;
  const items = [isMobile() ? null : {head: tr('Notifications for this task')},  // a phone sheet has it as its title
    {label: tr('As the project'), icon: 'bell', on: lv === 'list', title: tr('Follows the project bell and Settings > Notifications'), fn: () => tbl_set(tid, 'list')},
    {label: tr('Muted'), icon: 'belloff', on: lv === 'mute', title: tr('No pushes for this task; News stay'), fn: () => tbl_set(tid, 'mute')},
    {label: tr('Urgent until completed'), icon: 'bellring', on: lv === 'urgent' && !m.until, fn: () => tbl_set(tid, 'urgent')},
    {label: tr('Urgent until a date…'), icon: 'cal', on: lv === 'urgent' && !!m.until, fn: () => tbl_untilAsk(tid, m.until)}];
  if (lv === 'urgent') items.push('-', {label: (foreign ? tr('Urgent, set by {0}', m.by_name || '?') : tr('Urgent|bell')) + ' · ' + tbl_untilTxt(m) +
    (m.active === false ? ' · ' + (foreign && !j.accept ? tr('you do not accept urgent markings from others') : tr('not active')) : ''), cls: 'tbl-st', dis: true});
  if (j.can_others) items.push('-', {label: tr('Urgent for others…'), icon: 'users', fn: () => tbl_others(tid)});
  items.push('-', {label: tbl_hint(), cls: 'tbl-hint', dis: true});
  menu(anchor, items, null, null, tr('Notifications for this task'));
}
async function tbl_untilAsk(tid, cur) {
  const v = await askPrompt(tr('Urgent until'), cur || addDays(today(), 1), {input: {type: 'date'}, ok: tr('Mark urgent')});
  if (!v) return;
  if (v < today()) { toast(tr('The date is in the past')); return; }
  tbl_set(tid, 'urgent', v);
}
// the list's owner / admins: who of the list gets "Urgent" (ticked = urgent after OK; untick = take back what others set)
async function tbl_others(tid) {
  const j = await tbl_load(tid, true);
  if (!j?.can_others) return;
  const ppl = j.people || [], mine = j.mine;
  const isOn = p => p.level === 'urgent';
  const row = (p, i) => `<label class="chkl tbl-p"><input type="checkbox" data-tblp="${p.id}" ${isOn(p) ? 'checked' : ''} ${p.level === 'urgent' && p.set_by === p.id ? 'disabled' : ''}> ${esc(p.name)}${p.level === 'mute' ? ` <span class="muted">· ${esc(tr('Muted'))}</span>` : ''}${p.level === 'urgent' && p.set_by === p.id ? ` <span class="muted">· ${esc(tr('own choice'))}</span>` : ''}</label>`;
  let md = null;
  const ok = await askDialog({title: tr('Urgent for others'), ok: tr('Save'),
    html: `<p class="muted">${esc(tr('Everyone ticked gets every change and comment of this task as an urgent push and a News item. Each person can switch it off for themselves.'))}</p>
      <label class="chkl tbl-all"><input type="checkbox" id="tbl-all"> <b>${esc(tr('All people of the project'))}</b></label>
      <label class="chkl tbl-p"><input type="checkbox" data-tblp="${S.me?.id}" ${mine.level === 'urgent' ? 'checked' : ''}> ${esc(tr('Me'))}</label>
      ${ppl.map(row).join('')}
      <div class="row tbl-until"><label>${esc(tr('Until (empty = until completed)'))}</label>${dateIn('tbl-u', '', {label: tr('Until (empty = until completed)'), min: today()})}</div>`,
    after: d => {
      md = d;
      const all = $('#tbl-all', d), boxes = () => $$('[data-tblp]:not([disabled])', d);
      const sync = () => { const b = boxes(); all.checked = b.length > 0 && b.every(x => x.checked); };
      all.addEventListener('change', () => { for (const x of boxes()) x.checked = all.checked; });
      d.addEventListener('change', e => { if (e.target.matches('[data-tblp]')) sync(); });
      sync();
    }});
  if (!ok || !md) return;
  const until = $('#tbl-u', md)?.value || null;
  if (until && until < today()) { toast(tr('The date is in the past')); return; }
  const was = new Map([[S.me?.id, mine], ...ppl.map(p => [p.id, p])]);
  const on = [], off = [];
  for (const x of $$('[data-tblp]:not([disabled])', md)) {
    const id = +x.dataset.tblp, p = was.get(id) || {};
    if (x.checked && (p.level !== 'urgent' || (until || null) !== (p.until || null))) on.push(id);
    else if (!x.checked && p.level === 'urgent' && p.set_by && p.set_by !== id) off.push(id);
  }
  if (!on.length && !off.length) return;
  const acts = [];
  try {
    if (on.length) { const r = await tbl_req('PUT', `/api/tasks/${tid}/bell`, {level: 'urgent', until, users: on}); if (r.act) acts.push(r.act); tbl_cache()[tid] = r; }
    if (off.length) { const r = await tbl_req('PUT', `/api/tasks/${tid}/bell`, {level: 'list', users: off}); if (r.act) acts.push(r.act); tbl_cache()[tid] = r; }
  } catch { /* tbl_req said it */ }
  tbl_paint(tid);
  if (!acts.length) return;
  const label = on.length ? trn('Urgent for {0} person', 'Urgent for {0} people', on.length) : trn('Urgent taken back for {0} person', 'Urgent taken back for {0} people', off.length);
  let cur = acts;
  const e = histAdd({label,
    undo: async () => { let r; for (const act of [...cur].reverse()) r = await tbl_req('POST', `/api/tasks/${tid}/bell/undo`, {act}); if (r) { tbl_cache()[tid] = r; tbl_paint(tid); } },
    redo: async () => { const n = []; let r;
      if (on.length) { r = await tbl_req('PUT', `/api/tasks/${tid}/bell`, {level: 'urgent', until, users: on}); if (r.act) n.push(r.act); }
      if (off.length) { r = await tbl_req('PUT', `/api/tasks/${tid}/bell`, {level: 'list', users: off}); if (r.act) n.push(r.act); }
      cur = n; if (r) { tbl_cache()[tid] = r; tbl_paint(tid); } }});
  offerUndo(label, e);
}

// the history line (collab.js actText0) and the News item (collab.js newsText)
function tbl_actText(d, who) {
  if (d.undo) return tr('{0} undid a change of the urgent marking', who);
  if (d.self) return tr('{0} switched off the urgent marking for themselves', who);
  if (d.level === 'urgent') return trn('{1} marked the task urgent for {0} person', '{1} marked the task urgent for {0} people', d.n || 1, who) + (d.until ? ' · ' + esc(tr('until {0}', fmtDateLoc(d.until))) : '');
  return trn('{1} took back the urgent marking for {0} person', '{1} took back the urgent marking for {0} people', d.n || 1, who);
}
function tbl_newsText(it, who) {
  const d = it.data || {};
  return tr('{0} marked a task urgent for you', who) + (d.until ? ' · ' + esc(tr('until {0}', fmtDateLoc(d.until))) : '');
}
// Settings > Notifications: accept urgent markings from others (default on)
const tbl_setHtml = (chk, hint) => typeof collab === 'function' && collab() ? `<h4 id="s-tbl-h">${tr('Urgent tasks')}</h4>
      <div class="row">${chk('s-tblacc', S.settings?.tbl_accept !== '0', tr('Accept urgent markings from others'))}</div>
      ${hint(tr('An admin of a project can mark a task urgent for you: every change and comment then comes as a push at the highest priority. Switched off, such a marking counts as “As the project” for you (it stays visible on the task).'))}` : '';

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-tblb]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); tbl_menu(b, +b.dataset.tblb);
}, true);
