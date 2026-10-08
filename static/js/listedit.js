/* Kalmido web client: List editing, keyboard reordering, recent lists.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.0.2: list editing, keyboard, recently viewed, list icons, agent typing
// ---- #182 edit a title right in the list: double-click (desktop) or E / F2 on the keyboard-focused row. Enter saves (one
// undo step), Esc cancels, leaving the field saves. A re-render (sync) keeps the field, its text and the caret.
S.ie = null;  // {id, v, s, e}
function inlineEditStart(id) {
  const t = taskById(id);
  if (!t || !(t.id > 0)) return;
  if (!canEdit(t)) { roToast(); return; }
  if (!$(`#view .trow[data-id="${id}"] .ttl`)) return;
  if (S.ie && S.ie.id !== id) inlineEditCommit();
  S.ie = {id, v: t.title};
  inlineEditMount(true);
}
function inlineEditMount(focus) {
  const ie = S.ie; if (!ie) return;
  const row = $(`#view .trow[data-id="${ie.id}"]`), ttl = row && $('.ttl', row);
  if (!ttl) return;
  if ($('.ttlin', ttl)) return;
  row.classList.add('iedit'); row.removeAttribute('draggable');
  ttl.removeAttribute('role'); ttl.removeAttribute('tabindex');  // 2.16.0 (#473): no field inside a button
  ttl.innerHTML = `<input class="ttlin" value="${esc(ie.v)}" aria-label="${esc(tr('Title'))}" maxlength="500" enterkeyhint="done" autocomplete="off">`;
  const i = $('.ttlin', ttl);
  i.addEventListener('input', () => { ie.v = i.value; });
  i.addEventListener('keydown', e => {
    if (e.isComposing) return;
    if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); inlineEditCommit(true); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); inlineEditCancel(); }
    else e.stopPropagation();  // j / k / x … are text here
  });
  i.addEventListener('blur', () => setTimeout(() => { if (S.ie === ie && !(document.activeElement && document.activeElement.classList.contains('ttlin'))) inlineEditCommit(); }, 0));
  if (focus) { i.focus(); const s = ie.s ?? i.value.length, en = ie.e ?? i.value.length; try { i.setSelectionRange(s, en); } catch { /* ignore */ } }
}
async function inlineEditCommit(keepFocus) {
  const ie = S.ie; if (!ie) return;
  S.ie = null;
  const t = taskById(ie.id), v = String(ie.v || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  if (t && v && v !== t.title) {
    try { await patchUndoable(ie.id, {title: v}, tr('Renamed to {0}', qn(v.slice(0, 40)))); } catch { /* api() showed it */ }
  }
  renderView();
  if (keepFocus) kfocus(ie.id);
}
function inlineEditCancel() { const ie = S.ie; S.ie = null; renderView(); if (ie) kfocus(ie.id); }
document.addEventListener('dblclick', e => {
  const r = e.target.closest?.('#view .trow');
  if (!r || isTouch() || S.multiMode || !e.target.closest('.tmain') || e.target.closest('button,a,input,.ttlin')) return;
  e.preventDefault(); window.getSelection?.()?.removeAllRanges?.();
  inlineEditStart(+r.dataset.id);
});

// ---- #283 "+" on a section header: an input right below it, Enter adds the task there and stays open for the next one
S.secAdd = null;  // {key, sec, v}
function secAddOpen(sec) {
  // 2.13.4: phones get the quick sheet (its box sits above the keyboard) with the section set; the inline field under the
  // section head ended up behind the keyboard (Android: keyboard up, no box to type into)
  const rl = routeList();
  if (isMobile() && rl) {
    const g = S.sections.find(x => x.id === sec);
    openQuickSheet('', {list_id: rl.id, section_id: sec || null, section_name: g ? g.name : ''});
    return;
  }
  S.secAdd = {key: S.route.key, sec: sec || 0, v: ''};
  S.collapsed.delete('s:' + (sec || 0)); LS.set('collapsed', [...S.collapsed]);
  renderView();
  $('#view .secadd-in')?.focus();
}
function secAddHtml(g) {
  const sa = S.secAdd;
  if (!sa || sa.key !== S.route.key || sa.sec !== (g.section || 0)) return '';
  return `<div class="secadd">${ic('plus', 's')}<input class="secadd-in" data-sec="${g.section || 0}" placeholder="${esc(tr('Add a task to {0}', g.name))}" aria-label="${esc(tr('Add a task to {0}', g.name))}" enterkeyhint="done" autocomplete="off"></div>`;
}
async function secAddSubmit(inp) {
  const sa = S.secAdd, text = inp.value.trim(); if (!sa || !text) return;
  const lid = routeList()?.id; if (!lid) return;
  const r = parseQuick(text, new Set());
  inp.value = ''; sa.v = '';
  try {
    await createTask({title: (r.title || text).slice(0, 500), list_id: lid, section_id: sa.sec || null, due: r.due || null, due_time: r.due_time,
      priority: r.priority ?? 0, tags: r.tags || [], repeat: r.repeat || ''});
  } catch { inp.value = text; sa.v = text; }
  $('#view .secadd-in')?.focus();
}
document.addEventListener('keydown', e => {
  const i = e.target; if (!i.classList?.contains('secadd-in')) return;
  if (e.isComposing) return;
  if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); secAddSubmit(i); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); S.secAdd = null; renderView(); }
}, true);
document.addEventListener('input', e => { if (e.target.classList?.contains('secadd-in') && S.secAdd) S.secAdd.v = e.target.value; });
document.addEventListener('focusout', e => {
  const i = e.target; if (!i.classList?.contains('secadd-in')) return;
  setTimeout(() => { if (S.secAdd && !S.secAdd.v && !(document.activeElement && document.activeElement.classList.contains('secadd-in')) && !S.secAdd.keep) { S.secAdd = null; renderView(); } }, 150);
});

// ---- #284 collapse / expand everything of the view: section groups and tasks with subtasks (remembered per device)
function collapseKeys() {
  if (S.route.mod !== 'tasks' || isKanban() || isTimeline() || isRoadmap() || NOLIST_KEYS.includes(S.route.key)) return [];
  const keys = [], walk = t => { const k = children(t.id).filter(x => x.status === 0); if (k.length) { keys.push('t' + t.id); k.forEach(walk); } };
  for (const g of groupTasks(viewTasks())) { if (g.name) keys.push(g.id); g.tasks.forEach(walk); }
  return keys;
}
function collapseAll(close) {
  const keys = collapseKeys(); if (!keys.length) return;
  for (const k of keys) close ? S.collapsed.add(k) : S.collapsed.delete(k);
  LS.set('collapsed', [...S.collapsed]); renderView();
  toast(close ? tr('Everything collapsed') : tr('Everything expanded'));
}
const collapseAnyOpen = () => collapseKeys().some(k => !S.collapsed.has(k));
function collapseItems() {
  const keys = collapseKeys(); if (!keys.length) return [];
  const open = keys.some(k => !S.collapsed.has(k)), closed = keys.some(k => S.collapsed.has(k));
  return [{label: tr('Collapse all'), icon: 'chev', dis: !open, keys: 'Shift+C', fn: () => collapseAll(true)},
    {label: tr('Expand all'), icon: 'sub', dis: !closed, fn: () => collapseAll(false)}];
}

// ---- #184 recently viewed tasks and lists (per device, the last 5) on top of the command palette
function recentPush(kind, id) {
  if (!(id > 0)) return;
  const k = kind + ':' + id;
  LS.set('recentViewed', [k, ...LS.get('recentViewed', []).filter(x => x !== k)].slice(0, 5));
}
function palOpenTask(x) {
  const r = $(`#view .trow[data-id="${x.id}"]`);
  if (!r && x.list_id) go(x.list_id === inbox()?.id ? 'inbox' : 'l/' + x.list_id);
  setTimeout(() => openDetail(x.id), 30);
}
function palViewed() {
  return LS.get('recentViewed', []).map(k => {
    const [kind, v] = k.split(':'), id = +v;
    if (kind === 't') {
      const t = taskById(id); if (!t || t.deleted_at) return null;
      return {id: 'rv:' + k, kind: 'tasks', label: t.title, icon: t.status === 2 ? 'done' : 'check', group: 'viewed', fn: () => palOpenTask(t),
        sub: [lname(listById(t.list_id)), t.due ? dayLabel(t.due) : ''].filter(Boolean).join('  ·  ')};
    }
    if (kind === 'l') {
      const l = listById(id); if (!l || l.archived) return null;
      return {id: 'rv:' + k, kind: 'list', label: l.is_inbox ? tr('Inbox') : lname(l), icon: 'list', sw: cssColor(l.color), img: l.icon || '', group: 'viewed', fn: () => go(l.is_inbox ? 'inbox' : 'l/' + l.id)};
    }
    return null;
  }).filter(Boolean);
}

// ---- #245 own list icons: a picture instead of the emoji (presets: the app icon + the profile pictures, or an own picture, cropped
// square like the profile picture). Shown wherever the emoji / colour dot of the list shows. An emoji still works; picking
// one removes the picture and the other way round.
const LICON_PRESETS = [['kalmido', 'Kalmido'], ...AV_PRESETS];
const liconSrc = k => k === 'kalmido' ? '/static/icon.svg' : `/static/avatars/${k}.svg`;
const licon = (l, cls = 'licon') => l && l.icon ? `<img class="${cls}" src="${esc(l.icon)}" alt="" loading="lazy" decoding="async">` : '';
function liconPickHtml(l) {
  const cur = l.icon || '';
  return `<div class="lipick" role="group" aria-label="${esc(tr('Picture'))}">${LICON_PRESETS.map(([k, n]) => `<button type="button" class="avopt ${cur === liconSrc(k) ? 'on' : ''}" data-licon="${k}" title="${esc(k === 'kalmido' ? n : tr(n))}" aria-label="${esc(k === 'kalmido' ? n : tr(n))}" aria-pressed="${cur === liconSrc(k)}"><img src="${liconSrc(k)}" alt=""></button>`).join('')}` +
    `<button type="button" class="avopt up ${cur.startsWith('/api/list-icon/') ? 'on' : ''}" data-licon="upload" title="${esc(tr('Upload a picture…'))}" aria-label="${esc(tr('Upload a picture…'))}">${cur.startsWith('/api/list-icon/') ? `<img src="${esc(cur)}" alt="">` : ic('plus')}</button>` +
    (cur ? `<button type="button" class="avopt none" data-licon="none" title="${esc(tr('Remove the picture'))}" aria-label="${esc(tr('Remove the picture'))}">${ic('ban', 's')}</button>` : '') + '</div>';
}
async function liconSet(lid, how) {
  let j;
  try {
    if (how === 'none') j = await api('DELETE', `/api/lists/${lid}/icon`);
    else if (how instanceof Blob) { const fd = new FormData(); fd.append('file', how, 'icon.png'); j = await api('POST', `/api/lists/${lid}/icon`, fd); }
    else j = await api('PUT', `/api/lists/${lid}/icon`, {preset: how});
  } catch { return null; }
  const l = listById(lid); if (l) l.icon = j.icon || '';
  await load().catch(() => {}); render();
  return j.icon || '';
}
function liconUpload(lid) {
  return new Promise(res => {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
    inp.addEventListener('change', async () => {
      const f = inp.files?.[0]; if (!f) { res(null); return; }
      if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); res(null); return; }
      const bl = await avCropModal(f, {title: tr('List icon'), png: true, square: true}); if (!bl) { res(null); return; }
      res(await liconSet(lid, bl));
    });
    inp.click();
  });
}

// ---- #299 "Claude is writing …": while an agent reports "working", under the last chat message and in the comment area of
// the task it works on (status task_id, a running job on the task, else every task of its lists); a spinning ring on the
// header chip / the agents button everywhere; "waiting" = an accent dot instead
const workingAgents = () => (S.agents || []).filter(a => a.enabled && a.status === 'working');
function taskTypers(t) {
  if (!t || !(t.id > 0) || t.context) return [];
  const mine = new Set(taskAgents(t).map(a => a.id));
  const ags = workingAgents().filter(a => a.status_task === t.id || (a.job_tasks || []).includes(t.id) || (!a.status_task && mine.has(a.id)));
  // 2.22.0 (#693): people and agents that sent the typing signal for this task's comments (GET /api/version, ty)
  const ty = (S.ctyping || []).filter(x => x.task_id === t.id);
  return [...ags.map(a => ty.some(x => x.user_id === a.id) ? {...a, typing: Infinity} : a),
    ...ty.filter(x => !ags.some(a => a.id === x.user_id)).map(x => ({id: x.user_id, name: x.name, typing: Infinity}))];
}
// 2.22.0 (#693): while I write a comment in a shared list, the others see "<name> is writing …" (a signal every 5 s at most)
const CTY = {tid: 0, at: 0};
function commentTyping() {
  const t = taskById(S.sel); if (!t || !(t.id > 0) || !cmSocial(t) || !OUT.online) return;
  if (CTY.tid === t.id && Date.now() - CTY.at < 5000) return;
  CTY.tid = t.id; CTY.at = Date.now();
  fetch(`/api/tasks/${t.id}/typing`, {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).catch(() => {});
}
function typingHtml(ags, id) {
  if (!ags.length) return `<div class="atyping hidden" id="${id}" role="status" aria-live="polite"></div>`;
  // 2.13.2 (#478 F6): "is writing …" (dots) only for a real typing signal (or the chat's answer on its way); an agent that
  // only reports "working" on the task "is working on it"
  const wr = a => id === 'chat-typing' || (a.typing || 0) - agentAge() > 0, any = ags.some(wr);
  return `<div class="atyping" id="${id}" role="status" aria-live="polite">${any ? '<span class="atdots" aria-hidden="true"><i></i><i></i><i></i></span>' : hdot('working')}<span class="ttx">${ags.map(a => esc(wr(a) ? tr('{0} is writing …', a.name) : tr('{0} is working on it', a.name)) + (a.status_text ? ` <span class="muted">· ${esc(a.status_text)}</span>` : '')).join('<br>')}</span></div>`;
}
const agentBusyState = () => { const ags = (S.agents || []).filter(a => a.enabled && !agentOffline(a)); return ags.some(a => a.status === 'working') ? 'working' : ags.some(a => a.status === 'waiting' || a.waiting) ? 'waiting' : ''; };
const agentStatusLines = () => (S.agents || []).filter(a => a.enabled && a.status !== 'idle').map(agentHstLine);  // 2.13.0 (#453 P10): no stale status text while not connected
// live update without re-rendering what someone may be typing in (task panel, chat)
function agentLive() {
  chatFabDraw();  // 2.29.0 (#363): the pop-up button follows the agents (unread count, last agent, module on / off)
  const t = S.sel && taskById(S.sel), d = $('#d-typing');
  if (d) d.outerHTML = typingHtml(taskTypers(t), 'd-typing');
  // 2.12.2 (#451): the typing row and the state chip are swapped only when they changed; the dots appearing make the list
  // shorter, so a list that was at the bottom is put back to the bottom
  const c = $('#chat-typing'), a = S.chat.aid && agentById(S.chat.aid), box = $('#chat-msgs'), pin = !!box && chatNear(box);
  const swap = (el, h) => { if (el && el._h !== h && el.outerHTML !== h) { el.outerHTML = h; const n = $('#' + el.id); if (n) n._h = h; } };
  if (c) swap(c, typingHtml(chatTyping(a) ? [a] : [], 'chat-typing'));
  if (a) swap($('#chat-st'), chatStHtml(a));
  if (pin && box.isConnected && !chatNear(box)) box.scrollTop = box.scrollHeight;
  const st = agentBusyState();
  const more = $('#tabs [data-act="tabs-more"]'), inMore = !!more && tabOverflow().more.some(x => x.id === 'agents');
  // 2.23.0 (#824): a small pulsing dot at the icon instead of a spinning ring (looked like a stuck loader), and the label says who
  const wk = (S.agents || []).find(a => a.enabled && !agentOffline(a) && a.status === 'working'), lab = wk ? tr('{0} is working', wk.name) : '';
  const mark = (b, on, w) => { b.classList.toggle('aspin', on); b.classList.toggle('await', w); if (!('alab' in b.dataset)) b.dataset.alab = b.getAttribute('aria-label') || ''; const base = b.dataset.alab || b.textContent.trim(); if (on) b.setAttribute('aria-label', base + ' · ' + lab); else if (b.dataset.alab) b.setAttribute('aria-label', b.dataset.alab); else b.removeAttribute('aria-label'); };
  $$('#side [data-go="agents"], #tabs [data-go="agents"]').forEach(b => mark(b, st === 'working', st === 'waiting'));
  if (more) mark(more, st === 'working' && inMore, st === 'waiting' && inMore);
}
// 2.4.1 (#375): an open chat's header follows the clock too (a typing signal runs out after 10 s, "offline" after 5 minutes
// without a poll), without asking the server
setInterval(() => { if (S.chat.aid && !document.hidden && $('#chat-st')) agentLive(); }, 2000);
// 2.6.1 (#402): the header dots follow the clock too ("offline" once an agent stopped polling), without asking the server
let hdSig = '';
// 2.27.0 (#1007): the dots, the list's agent band and the chat said different things ("not connected" vs. "ready"): the
// age of the last contact counted on from the last full state load, which only comes when data changes. Now the agents'
// status is asked again (GET /api/agents) once it is older than a minute, then the header AND the band follow
setInterval(async () => {
  if (document.hidden || !$('#top')) return;
  if (agentsOn() && Date.now() - (S.agentsAt || 0) > 60000) await agentPoll();
  const sg = shownAgents().map(a => a.id + agentHst(a)).join(); if (sg === hdSig) return;
  const first = !hdSig; hdSig = sg; if (first) return;
  renderTop(); if ($('#view .agband')) viewSafeRender();
}, 30000);
// sync while typing in the task panel: no full reload, but the agents' status still comes along
async function agentPoll() {
  if (!agentsOn()) return;
  try { const j = await api('GET', '/api/agents'); if (Array.isArray(j.agents)) { S.agents = j.agents; S.agentsAt = Date.now(); agentLive(); renderTop(); } } catch { /* offline */ }
}

// ---- #285 drag and drop (desktop): scroll the list / sidebar when the pointer comes near the top or bottom edge
// (faster the closer it gets); also left / right in the kanban board
const DS = {on: false, x: 0, y: 0, box: null, raf: 0, last: 0};
const DS_EDGE = 64, DS_MAX = 22;
function dsScrollable(el) {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if ((/(auto|scroll)/.test(cs.overflowY) && n.scrollHeight > n.clientHeight + 1) || (/(auto|scroll)/.test(cs.overflowX) && n.scrollWidth > n.clientWidth + 1)) return n;
  }
  return null;
}
// speed (px per frame) for a pointer at p inside [a, b]: 0 outside the edge zones, up to DS_MAX at (or beyond) the edge
function dsSpeed(p, a, b) {
  const edge = Math.min(DS_EDGE, (b - a) / 4);
  if (p < a + edge) return -Math.ceil(DS_MAX * Math.min(1, (a + edge - p) / edge));
  if (p > b - edge) return Math.ceil(DS_MAX * Math.min(1, (p - (b - edge)) / edge));
  return 0;
}
function dsStep() {
  DS.raf = 0;
  if (!DS.on || !DS.box || !DS.box.isConnected) return;
  const r = DS.box.getBoundingClientRect();
  let moved = false;
  if (DS.x >= r.left - 40 && DS.x <= r.right + 40 && DS.box.scrollHeight > DS.box.clientHeight + 1) {
    const v = dsSpeed(DS.y, r.top, r.bottom);
    if (v) { const b = DS.box.scrollTop; DS.box.scrollTop = b + v; moved = DS.box.scrollTop !== b; }
  }
  if (DS.y >= r.top && DS.y <= r.bottom && DS.box.scrollWidth > DS.box.clientWidth + 1 && /(auto|scroll)/.test(getComputedStyle(DS.box).overflowX)) {
    const v = dsSpeed(DS.x, r.left, r.right);
    if (v) { const b = DS.box.scrollLeft; DS.box.scrollLeft = b + v; moved = moved || DS.box.scrollLeft !== b; }
  }
  if (moved || Date.now() - DS.last < 400) DS.raf = requestAnimationFrame(dsStep);
}
document.addEventListener('dragstart', e => { if (isTouch() && isMobile()) return; if (e.target.closest?.('#view, #side')) { DS.on = true; DS.box = null; } }, true);
document.addEventListener('dragover', e => {
  if (!DS.on) return;
  DS.x = e.clientX; DS.y = e.clientY; DS.last = Date.now();
  const box = dsScrollable(e.target);
  if (box && (box.closest('#view') || box.id === 'view' || box.id === 'side')) DS.box = box;
  else if (!DS.box) DS.box = $('#view');
  if (!DS.raf) DS.raf = requestAnimationFrame(dsStep);
}, true);
const dsStop = () => { DS.on = false; DS.box = null; if (DS.raf) cancelAnimationFrame(DS.raf); DS.raf = 0; };
document.addEventListener('dragend', dsStop, true);
document.addEventListener('drop', dsStop, true);
