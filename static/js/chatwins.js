/* Kalmido web client: several chats at once in the chat side panel, one above the other (2.47.1, #1720).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Desktop: the side panel #achat holds a list of windows S.cw.wins = [{k: 'a:<agent id>' | 't:<room id>', h: share, c: folded}],
// one above the other with a draggable divider between two of them. One agent window and one team window are "live": they
// carry the usual ids (#chat-in, #chat-msgs, …, #tc-in, #tc-msgs, …) and S.chat / the room fields of S.tc are their state, so
// every existing function works on them unchanged. The other windows are parked: drawn from their own state (S.cw.st) with
// the ids renamed to data-cwid. The first pointer / focus in a parked window makes it live (ids and state swap, nothing is
// redrawn, the click goes on). A team window that is live in the panel parks the conversation of the team view the same way
// (its state waits in S.cw.home). One agent window = the panel exactly as before. Phones / tablets (chatFull): no split, a
// row with the open chats above the chat switches between them.
const CW_MIN = 220;  // px: the smallest height of an open window; more windows than fit fold to their header
S.cw = {wins: [], act: '', st: {}, lt: '', home: null};
const CW_TF = ['rid', 'room', 'msgs', 'more', 'edit'];
const cw_tcGet = () => Object.fromEntries(CW_TF.map(f => [f, S.tc[f]]));
const cw_tcPut = o => { for (const f of CW_TF) S.tc[f] = o ? o[f] : (f === 'msgs' ? [] : null); };
const cw_id = k => +k.slice(2);
const cw_has = k => S.cw.wins.some(w => w.k === k);
const cw_win = k => S.cw.wins.find(w => w.k === k);
const cw_sec = k => k ? $(`#achat .cwin[data-cw="${k}"]`) : null;
const cw_isLive = k => k[0] === 'a' ? S.chat.aid === cw_id(k) : S.cw.lt === k;
// the panel needs window frames: more than one window, or a team chat in it (it has no close button of its own)
const cw_framed = () => S.cw.wins.length > 1 || S.cw.wins.some(w => w.k[0] === 't');
const cw_docked = () => { const p = $('#achat'); return !!p && !p.classList.contains('hidden') && !p.classList.contains('float') && !chatFull(); };
const cw_noIds = h => h.replace(/(\s)id="/g, '$1data-cwid="');
function cw_idsOff(el) { if (el) for (const n of el.querySelectorAll('[id]')) { n.dataset.cwid = n.id; n.removeAttribute('id'); } }
function cw_idsOn(el) { if (el) for (const n of el.querySelectorAll('[data-cwid]')) { n.id = n.dataset.cwid; delete n.dataset.cwid; } }
let cw_ren = '';  // the panel window being drawn (its header buttons)

// the state of a window's chat: the live one is S.chat / S.tc, a parked one its own
function cw_stOf(k) {
  if (k[0] === 'a') return S.chat.aid === cw_id(k) ? S.chat : (S.cw.st[k] ||= {aid: cw_id(k), msgs: [], err: null});
  if (S.cw.lt === k) return S.tc;
  return S.cw.st[k] ||= {rid: cw_id(k), room: null, msgs: [], more: false, edit: null};
}
// draws with a parked window's state in S.chat / S.tc (synchronous functions only)
function cw_with(k, fn) {
  if (cw_isLive(k)) return fn();
  const st = cw_stOf(k);
  if (k[0] === 'a') { const keep = S.chat; S.chat = st; try { return fn(); } finally { S.chat = keep; } }
  const keep = cw_tcGet(); cw_tcPut(st); try { return fn(); } finally { cw_tcPut(keep); }
}

// ---- remembered per device (the open chats and their heights) for the account that opened them
let cw_saved = '';
function cw_save() {
  if (!S.me) return;
  const o = JSON.stringify({u: S.me.id, open: !!S.cw.wins.length && cw_docked(), wins: S.cw.wins.map(w => ({k: w.k, h: Math.round((w.h || 1) * 100) / 100, c: w.c === true}))});
  if (o !== cw_saved) { cw_saved = o; LS.set('cwins', JSON.parse(o)); }
}
async function cw_restore() {
  const o = LS.get('cwins', null); if (!o || o.u !== S.me?.id || !Array.isArray(o.wins) || !o.wins.length) return;
  if (o.wins.some(w => /^t:/.test(w.k)) && teamOn() && S.tc.rooms === null) await loadTeam();
  // only chats this person may still open (an agent that is gone / paused, a conversation no longer shared: dropped quietly)
  const ok = k => /^a:\d+$/.test(k) ? !!agentById(cw_id(k))?.enabled && feat('agents') : /^t:\d+$/.test(k) && teamOn() && (S.tc.rooms || []).some(r => r.id === cw_id(k));
  const wins = o.wins.filter((w, i, a) => w && ok(w.k) && a.findIndex(x => x.k === w.k) === i).map(w => ({k: w.k, h: +w.h > 0 ? +w.h : 1, c: !!w.c}));
  if (!wins.length || S.cw.wins.length) return;
  S.cw.wins = wins; S.cw.act = wins[0].k;
  if (chatFull()) { cw_swSync(); return; }  // the phone's row of open chats
  // the panel opens again only with window frames (one agent chat: as before, it stays closed after a reload)
  if (!o.open || !cw_framed() || chatFloatOn() || $('#achat:not(.hidden)')) return;
  const a = wins.find(w => w.k[0] === 'a');
  if (a) chatOpen(cw_id(a.k)); else cw_show();
}
{ const t = setInterval(() => { if (!S.booted || !S.me) return; clearInterval(t); cw_restore(); }, 400); }

// ---- the list changes: chatOpen() (normal open: replaces the active window; o.split: one more window), a team window
function cw_note(k, o = {}) {
  const W = S.cw.wins, i = W.findIndex(w => w.k === k);
  if (i >= 0) { if (W[i].c) W[i].c = false; }
  else if (o.split || !W.length) W.splice(W.findIndex(w => w.k === S.cw.act) + 1 || W.length, 0, {k, h: 1, c: false});
  else { const j = Math.max(0, W.findIndex(w => w.k === S.cw.act)); cw_drop(W[j].k); W[j] = {k, h: W[j].h || 1, c: false}; }
  // the agent that was live stays open: its state is kept (parked); the one opened takes its kept state
  if (k[0] === 'a' && S.chat.aid && S.chat.aid !== cw_id(k)) {
    if (cw_has('a:' + S.chat.aid)) { cw_idsOff(cw_sec('a:' + S.chat.aid)); S.cw.st['a:' + S.chat.aid] = S.chat; }
    if (S.cw.st[k]) { S.chat = S.cw.st[k]; delete S.cw.st[k]; }
  }
  S.cw.act = k; cw_fit(k); cw_save();
}
function cw_drop(k) {  // a window leaves the list: its kept state goes, a live team window gives the team view its state back
  delete S.cw.st[k];
  if (S.cw.lt === k) { cw_tcPut(S.cw.home); S.cw.home = null; S.cw.lt = ''; cw_idsOn($('#view .tcroom')); }
}
// "Open in split window" (menus, Ctrl / Cmd + click)
function cw_split(k) {
  if (k[0] === 'a') { const a = agentById(cw_id(k)); if (!a?.enabled) return; chatOpen(a.id, {split: true, float: false}); return; }
  cw_note(k, {split: true});
  if (chatFull()) { go('team/' + cw_id(k)); return; }
  cw_show();
}
// the docked panel shown for a team window (chatOpen does the same for an agent)
function cw_show() {
  tch_overlaysClose();
  if (document.body.classList.contains('chat-yield') && S.sel) closeDetail();
  let p = $('#achat');
  if (!p) { p = document.createElement('aside'); p.id = 'achat'; p.setAttribute('aria-label', tr('Chat')); document.body.appendChild(p); }
  if (p.classList.contains('float')) { LS.set('chatFloat', '0'); p.innerHTML = ''; delete p.dataset.aid; delete p.dataset.cw; }
  p.classList.remove('float', 'min', 'hidden'); p.style.left = p.style.top = p.style.right = p.style.bottom = '';
  document.body.classList.remove('chat-float'); document.body.classList.add('chat-open');
  fitLayout(); chatDraw(); chatFabDraw(); cw_save();
}
// chatClose(): the panel closes with all its windows (on the phone the row of open chats stays)
function cw_reset() {
  if (chatFull()) return;
  cw_tcPark(); S.cw.wins = []; S.cw.st = {}; S.cw.act = ''; cw_save();
  const p = $('#achat'); if (p?.classList.contains('cwsplit')) { p.classList.remove('cwsplit'); p.innerHTML = ''; delete p.dataset.cw; }
}
// one window closes (its X, Esc in it, the menu)
function cw_close(k) {
  const W = S.cw.wins, i = W.findIndex(w => w.k === k); if (i < 0) return;
  if (W.length === 1) { chatClose(); return; }
  W.splice(i, 1); cw_drop(k);
  if (S.cw.act === k) S.cw.act = (W[i] || W[i - 1]).k;
  if (k[0] === 'a' && S.chat.aid === cw_id(k)) S.chat = {aid: null, msgs: [], err: null};
  cw_fit(S.cw.act); cw_save(); chatDraw();
  setTimeout(() => $(`#achat .cwin[data-cw="${S.cw.act}"] textarea:not([disabled])`)?.focus({preventScroll: true}), 0);
}

// ---- drawing. chatDraw() asks first: true = the frames are drawn (the live agent window is then patched as usual)
function cw_frame(p) {
  cw_save();  // the panel was opened / closed (only written when something changed)
  if (!p || p.classList.contains('hidden') || p.classList.contains('float') || chatFull()) return false;
  if (!cw_framed()) {
    const w = S.cw.wins[0];  // back to one agent window: it is the live one (drawn as before)
    if (w && S.chat.aid !== cw_id(w.k)) { S.chat = cw_stOf(w.k); delete S.cw.st[w.k]; }
    if (p.classList.contains('cwsplit')) { p.classList.remove('cwsplit'); p.innerHTML = ''; delete p.dataset.cw; delete p.dataset.aid; }
    return false;
  }
  const sig = S.cw.wins.map(w => w.k).join(',');
  if (p.classList.contains('cwsplit') && p.dataset.cw === sig && p.querySelector('.cwin')) { cw_syncIds(); return false; }
  cw_draw(); return true;
}
function cw_pick() {  // the live agent window (S.chat) and the live team window are among the open ones
  const W = S.cw.wins, act = cw_win(S.cw.act);
  if (!S.chat.aid || !cw_has('a:' + S.chat.aid)) {
    const ak = (act?.k[0] === 'a' ? act : W.find(w => w.k[0] === 'a'))?.k;
    S.chat = ak ? cw_stOf(ak) : {aid: null, msgs: [], err: null}; if (ak) delete S.cw.st[ak];
  }
  if (S.cw.lt && !cw_has(S.cw.lt)) cw_drop(S.cw.lt);
  if (!S.cw.lt && !$('#view #tc-msgs')) {
    const tk = (act?.k[0] === 't' ? act : W.find(w => w.k[0] === 't'))?.k;
    if (tk) { S.cw.home = cw_tcGet(); cw_tcPut(cw_stOf(tk)); delete S.cw.st[tk]; S.cw.lt = tk; }
  }
}
function cw_winHtml(w) {
  const live = cw_isLive(w.k), id = cw_id(w.k), t = w.k[0] === 't';
  cw_ren = w.k;
  let h;
  try { h = t ? cw_with(w.k, tcRoomHtml) : cw_with(w.k, () => chatInner(id)); } finally { cw_ren = ''; }
  // the person's colour (#1721, core.js ac_color) as a thin line on top of the header; team chats without a person: none
  const room = t && (S.tc.rooms || []).find(r => r.id === id), uid = t ? room?.kind === 'dm' && room.user_id : id;
  const col = uid && typeof ac_color === 'function' ? ac_color(uid) : '';
  return `<section class="cwin${t ? ' tcroom' : ''}${w.c ? ' cwc' : ''}${S.cw.act === w.k ? ' cwact' : ''}${col ? ' cwcol' : ''}" data-cw="${w.k}" style="flex-grow:${w.h || 1}${col ? ';--cwcol:' + esc(col) : ''}" aria-label="${esc(cw_name(w.k))}">${live ? h : cw_noIds(h)}</section>`;
}
const cw_sepHtml = i => `<div class="cwsep" role="separator" aria-orientation="horizontal" tabindex="0" data-cwsep="${i}" aria-label="${esc(tr('Resize the chats'))}" title="${esc(tr('Drag to resize, double-click to share the height evenly'))}"></div>`;
function cw_draw() {
  const p = $('#achat'); if (!p) return;
  cw_pick(); cw_fit(S.cw.act);
  p.classList.add('cwsplit'); p.classList.toggle('cwmany', S.cw.wins.length > 1); delete p.dataset.aid; p.dataset.cw = S.cw.wins.map(w => w.k).join(',');
  p.innerHTML = S.cw.wins.map((w, i) => (i ? cw_sepHtml(i) : '') + cw_winHtml(w)).join('');
  for (const b of p.querySelectorAll('.cwin .chmsgs')) b.scrollTop = b.scrollHeight;
  for (const w of S.cw.wins) cw_loadIf(w.k);
}
function cw_syncIds() { for (const w of S.cw.wins) { const s = cw_sec(w.k); if (s) (cw_isLive(w.k) ? cw_idsOn : cw_idsOff)(s); } }
// a window's messages, freshly loaded when it was never loaded (open windows only)
function cw_loadIf(k) {
  const w = cw_win(k); if (!w || w.c) return;
  if (k[0] === 'a') { if (!cw_isLive(k) && !cw_stOf(k).loaded) cw_aload(k); return; }
  if (!cw_stOf(k).room) cw_tload(k);
}
const cw_name = k => k[0] === 'a' ? agentById(cw_id(k))?.name || '' : roomName((S.tc.rooms || []).find(r => r.id === cw_id(k)) || cw_stOf(k).room) || '';
function cw_unread(k) {
  if (k[0] === 'a') return (agentById(cw_id(k))?.chat_unread || 0) > 0;
  const r = (S.tc.rooms || []).find(x => x.id === cw_id(k)); return !!r && r.unread > 0;
}
// the header buttons of a panel window (chatInner / tcRoomHtml ask): unread dot, fold, the window menu (+ close for a team chat)
function cw_headBtns(k) {
  if (cw_ren !== k) return '';
  const w = cw_win(k), f = !!w?.c, lab = f ? tr('Unfold') : tr('Fold');
  return `<span class="cwdot" ${cw_unread(k) ? '' : 'hidden'} title="${esc(tr('Unread messages'))}" aria-label="${esc(tr('Unread messages'))}"></span>`
    + (S.cw.wins.length > 1 ? `<button type="button" class="iconbtn cwfold" data-cwact="fold" aria-expanded="${!f}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('chev', 's')}</button><button type="button" class="iconbtn" data-cwact="menu" aria-haspopup="menu" title="${esc(tr('Window'))}" aria-label="${esc(tr('Window'))}">${ic('dots', 's')}</button>` : '')
    + (k[0] === 't' ? `<button type="button" class="iconbtn" data-cwact="close" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button>` : '');
}
function cw_headSync(k) { const s = cw_sec(k), d = s && $('.cwdot', s); if (d && d.hidden === cw_unread(k)) d.hidden = !cw_unread(k); }
// the messages of one window again (only that window: live ones patch as before, parked ones by their keys)
function cw_patch(k) {
  if (cw_isLive(k)) { if (k[0] === 'a') chatPatch(); else tcPatch(); cw_headSync(k); return; }
  const s = cw_sec(k), box = s && $('.chmsgs', s); if (!box) return;
  const near = chatNear(box);
  patchKids(box, cw_noIds(cw_with(k, k[0] === 'a' ? chatMsgs : tcMsgsHtml)));
  if (near) box.scrollTop = box.scrollHeight;
  cw_headSync(k);
}

// ---- loading the chats of parked windows (the live ones load as before)
async function cw_aload(k) {
  if (cw_isLive(k)) { chatLoad(); return; }
  const st = cw_stOf(k), aid = st.aid; if (st.busyL) return;
  st.busyL = true;
  try {
    const first = st.msgs.length ? st.msgs[0].id : 0;
    const j = await api('GET', `/api/agents/${aid}/chat?` + (first ? `after=${first - 1}` : `limit=${typeof CHAT_PAGE === 'number' ? CHAT_PAGE : 30}`));  // 2.65.0 (#1823): CHAT_PAGE lives in the agent chat module
    if (first) { const lo = j.messages.length ? j.messages[0].id : Infinity; st.msgs = [...st.msgs.filter(m => m.id < lo), ...j.messages]; }
    else { st.msgs = j.messages; st.more = !!j.has_more; }
    st.err = null; st.loaded = true; st.live = j.steps_live || []; st.apv = j.approvals_open || []; st.f8c_wait = 0;
    if (j.now) st.off = Date.now() - Date.parse(j.now);
    const a = agentById(aid); if (a) { if (j.agent) Object.assign(a, j.agent); a.chat_unread = 0; }
  } catch (e) {
    st.err = e instanceof Offline ? tr('Only available online.') : e.message;
    st.f8c_wait = Math.min(2 * (st.f8c_wait || 7500), 300000); st.f8c_until = Date.now() + st.f8c_wait;  // 2.58.0 (#1773): pause, doubling up to 5 minutes
  }
  finally { st.busyL = false; }
  cw_patch(k); renderTop();
}
async function cw_tload(k, st) {
  if (!st && cw_isLive(k)) { await loadRoom(cw_id(k)); tcPatch(true); cw_headSync(k); return; }
  st = st || cw_stOf(k); if (st.busyL) return;
  const rid = st.rid; let j;
  st.busyL = true;
  try { j = await rawFetch('GET', `/api/team/rooms/${rid}/messages`); }
  catch (e) { st.err = e instanceof Offline ? tr('The team chat is only available online.') : e.message; return; }
  finally { st.busyL = false; }
  st.room = j.room; st.more = j.has_more; st.msgs = j.messages; S.tc.users = {...S.tc.users, ...j.users};
  e2eFromCache(st.msgs);
  const last = st.msgs[st.msgs.length - 1], w = cw_win(k);
  if (w && !w.c && last && (!j.room.last_read || last.id > j.room.last_read) && !document.hidden) {  // seen in an open window = read
    try { const r = await rawFetch('POST', `/api/team/rooms/${rid}/read`, {last_id: last.id}); if (S.team) S.team.unread = r.unread; } catch { /* offline */ }
    const rr = (S.tc.rooms || []).find(x => x.id === rid); if (rr) { rr.unread = 0; rr.mention = false; }
    renderSide(); renderTabs();
  }
  if (w) cw_patch(k);
}
// agentLive() (the agents changed): parked agent windows with unread answers load them; folded ones show the dot
function cw_live() {
  for (const w of S.cw.wins) {
    if (w.k[0] !== 'a' || cw_isLive(w.k)) continue;
    if (!w.c && cw_unread(w.k) && !(cw_stOf(w.k).f8c_until > Date.now())) cw_aload(w.k); else cw_headSync(w.k);  // 2.58.0 (#1773): not while pausing after an error
  }
}
// teamChanged() (someone wrote / read): the panel's team windows whose conversation has a newer message, and the team view's
// conversation while a panel window holds the live ids
async function cw_teamLive() {
  for (const w of S.cw.wins) {
    if (w.k[0] !== 't') continue;
    const r = (S.tc.rooms || []).find(x => x.id === cw_id(w.k)), st = cw_stOf(w.k), last = st.msgs?.[st.msgs.length - 1];
    if (!w.c && r?.last && (!last || r.last.id !== last.id)) cw_tload(w.k); else cw_headSync(w.k);
  }
  const h = S.cw.home;
  // 2.58.0 (#1773): only when its conversation has a newer message
  const hr = h?.rid && (S.tc.rooms || []).find(x => x.id === h.rid), hl = h?.msgs?.[h.msgs.length - 1];
  if (S.cw.lt && h?.rid && S.route.mod === 'team' && (!hr?.last || !hl || hr.last.id !== hl.id)) { await cw_tload('t:' + h.rid, h); if (S.cw.lt && S.route.mod === 'team') renderView(); }
}
// the team view draws its own conversation (viewTeam asks): while a panel window is live, from the kept state, without ids
function cw_tcHome(fn) {
  if (!cw_docked()) { cw_tcPark(); return fn(); }  // the panel closed / floating / the phone: the team view has its state back
  const keep = cw_tcGet(), lt = S.cw.lt; cw_tcPut(S.cw.home); S.cw.lt = '';
  try { return cw_noIds(fn()); } finally { S.cw.home = cw_tcGet(); cw_tcPut(keep); S.cw.lt = lt; }
}
// the team view takes its conversation back (a click / focus in it, another conversation opened in it)
function cw_tcPark() {
  const k = S.cw.lt; if (!k) return;
  cw_idsOff(cw_sec(k)); S.cw.st[k] = cw_tcGet();
  cw_tcPut(S.cw.home); S.cw.home = null; S.cw.lt = '';
  cw_idsOn($('#view .tcroom'));
}
// teamRoute(): the phone keeps its row of open chats; the desktop's team view takes its conversation back when it opens one
// (true: leaving the team view while a panel window is live only clears the kept state, the live window stays as it is)
function cw_route(rid) {
  if (chatFull()) { cw_tcPark(); if (rid) cw_note('t:' + rid); return false; }  // park first: the room opened now must not land in the live window's state
  if (!rid && S.cw.lt) { S.cw.home = {rid: null, room: null, msgs: [], more: false, edit: null}; return true; }
  cw_tcPark(); return false;
}

// ---- activating: the first pointer / focus in a parked window makes it the live one
function cw_act(k) {
  if (S.cw.act !== k) { S.cw.act = k; for (const s of document.querySelectorAll('#achat .cwin')) s.classList.toggle('cwact', s.dataset.cw === k); }
  if (cw_isLive(k) || !cw_has(k)) return;
  if (k[0] === 'a') {
    const old = S.chat.aid ? 'a:' + S.chat.aid : '';
    if (old && cw_has(old)) { cw_idsOff(cw_sec(old)); S.cw.st[old] = S.chat; }
    S.chat = cw_stOf(k); delete S.cw.st[k]; cw_idsOn(cw_sec(k));
    chatLoad();
  } else {
    if (S.cw.lt) { cw_idsOff(cw_sec(S.cw.lt)); S.cw.st[S.cw.lt] = cw_tcGet(); }
    else { S.cw.home = cw_tcGet(); cw_idsOff($('#view .tcroom')); }
    const st = cw_stOf(k); cw_tcPut(st); delete S.cw.st[k]; S.cw.lt = k; cw_idsOn(cw_sec(k));
    if (S.tc.room?.kind === 'dm') e2eRoomDecrypt(S.tc.rid).then(() => { if (S.cw.lt === k) tcPatch(); });  // 2.42.0 (#909): encrypted DMs
  }
}
for (const ev of ['pointerdown', 'focusin']) document.addEventListener(ev, e => {
  const s = e.target.closest?.('#achat.cwsplit .cwin[data-cw]');
  if (s) cw_act(s.dataset.cw); else if (S.cw.lt && e.target.closest?.('#view .tcroom')) cw_tcPark();
}, true);

// ---- folding, heights, order
// more open windows than fit (CW_MIN each) fold to their header, the ones furthest from the active first; folded by this
// (c: 'auto') they open again when there is room
function cw_fit(keep) {
  if (chatFull()) return;
  const W = S.cw.wins, n = Math.max(1, Math.floor((innerHeight || 800) / CW_MIN));
  for (const w of W) if (w.c === 'auto') w.c = false;
  const open = W.filter(w => !w.c);
  if (open.length <= n) return;
  const ai = W.findIndex(w => w.k === keep);
  open.sort((a, b) => Math.abs(W.indexOf(b) - ai) - Math.abs(W.indexOf(a) - ai)).slice(0, open.length - n).forEach(w => { if (w.k !== keep) w.c = 'auto'; });
}
function cw_layout() {  // folds and heights without drawing again
  for (const w of S.cw.wins) {
    const s = cw_sec(w.k); if (!s) continue;
    s.classList.toggle('cwc', !!w.c); s.style.flexGrow = w.h || 1;
    const b = $('[data-cwact="fold"]', s); if (b) { const l = w.c ? tr('Unfold') : tr('Fold'); b.setAttribute('aria-expanded', !w.c); b.title = l; b.setAttribute('aria-label', l); }
    if (!w.c) cw_loadIf(w.k);
  }
}
function cw_fold(k, on) {
  const w = cw_win(k); if (!w) return;
  w.c = on ?? !w.c;
  if (!w.c) { cw_fit(k); const s = cw_sec(k), b = s && $('.chmsgs', s); if (b) setTimeout(() => { b.scrollTop = b.scrollHeight; }, 0); }
  cw_layout(); cw_save();
}
function cw_even() { for (const w of S.cw.wins) w.h = 1; cw_layout(); cw_save(); }
function cw_move(k, d) {
  const W = S.cw.wins, i = W.findIndex(w => w.k === k), j = i + d; if (i < 0 || j < 0 || j >= W.length) return;
  [W[i], W[j]] = [W[j], W[i]]; cw_save(); cw_draw();
  setTimeout(() => { const s = cw_sec(k); if (s) $('[data-cwact="menu"]', s)?.focus({preventScroll: true}); }, 0);
}
function cw_menu(anchor, k) {
  const W = S.cw.wins, i = W.findIndex(w => w.k === k), w = W[i]; if (!w) return;
  menu(anchor, [{label: tr('Move up'), icon: 'up', dis: i === 0, fn: () => cw_move(k, -1)},
    {label: tr('Move down'), icon: 'down', dis: i === W.length - 1, fn: () => cw_move(k, 1)},
    {label: w.c ? tr('Unfold') : tr('Fold'), icon: 'chev', fn: () => cw_fold(k)},
    {label: tr('Share the height evenly'), icon: 'menu', fn: cw_even},
    // the header buttons hidden in the split panel (app.css): a window of the browser, the floating chat window
    ...(typeof dw_chatOpen === 'function' && mw_ok() ? [{label: tr('Open in its own window'), icon: 'panel', fn: () => dw_chatOpen(k[0] === 'a' ? 'agents' : 'team', cw_id(k))}] : []),
    ...(k[0] === 'a' ? [{label: tr('Open as a window'), icon: 'expand', fn: () => { cw_act(k); chatDock(true); }}] : []), '-',
    {label: tr('Close'), icon: 'x', fn: () => cw_close(k)}]);
}
// the open windows above and below a divider (folded ones in between are skipped)
function cw_sepPair(sep) {
  const secs = [...$('#achat').querySelectorAll('.cwin')], at = +sep.dataset.cwsep;
  const up = secs.slice(0, at).reverse().find(s => !s.classList.contains('cwc')), dn = secs.slice(at).find(s => !s.classList.contains('cwc'));
  return up && dn ? [up, dn] : null;
}
// moves the border between two open windows by dy px from where it was at the start (each keeps CW_MIN at least, if it can)
function cw_resizer(up, dn) {
  const hu = up.getBoundingClientRect().height, tot = hu + dn.getBoundingClientRect().height, lo = Math.min(CW_MIN, tot / 2);
  const wu = cw_win(up.dataset.cw), wd = cw_win(dn.dataset.cw), sum = (wu.h || 1) + (wd.h || 1);
  return dy => { wu.h = sum * Math.max(lo, Math.min(tot - lo, hu + dy)) / tot; wd.h = sum - wu.h; up.style.flexGrow = wu.h; dn.style.flexGrow = wd.h; };
}
document.addEventListener('pointerdown', e => {
  const sep = e.target.closest?.('#achat .cwsep'); if (!sep || e.button !== 0) return;
  const pr = cw_sepPair(sep); if (!pr) return;
  e.preventDefault(); sep.setPointerCapture?.(e.pointerId); sep.classList.add('on');
  const y0 = e.clientY, rs = cw_resizer(pr[0], pr[1]);
  const mv = ev => rs(ev.clientY - y0);
  const up = () => { sep.removeEventListener('pointermove', mv); sep.removeEventListener('pointerup', up); sep.removeEventListener('pointercancel', up); sep.classList.remove('on'); cw_save(); };
  sep.addEventListener('pointermove', mv); sep.addEventListener('pointerup', up); sep.addEventListener('pointercancel', up);
});
document.addEventListener('dblclick', e => { if (e.target.closest?.('#achat .cwsep')) { e.preventDefault(); cw_even(); } });
document.addEventListener('keydown', e => {
  const sep = e.target.closest?.('#achat .cwsep');
  if (sep && ['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) {
    const pr = cw_sepPair(sep); if (!pr) return;
    e.preventDefault(); cw_resizer(pr[0], pr[1])({ArrowUp: -24, ArrowDown: 24, Home: -9999, End: 9999}[e.key]); cw_save(); return;
  }
  if (sep && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); cw_even(); }
});
// Esc in a window of the split panel closes only that window (window capture: before agentchat.js closes the whole panel)
window.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.defaultPrevented || isMobile() || e.isComposing) return;
  const s = e.target.closest?.('#achat.cwsplit .cwin[data-cw]'); if (!s || !e.target.matches('#chat-in, #tc-in, [data-cwid="chat-in"], [data-cwid="tc-in"]') || $('.modal, .pop:not(.hidden), .mpick:not(.hidden)')) return;
  e.preventDefault(); e.stopPropagation(); cw_close(s.dataset.cw);
}, true);
// drag a window by its header to another place (the menu has Move up / down for the keyboard)
document.addEventListener('pointerdown', e => {
  const h = e.target.closest?.('#achat.cwsplit .cwin > .chath, #achat.cwsplit .cwin > .tcrhead');
  if (!h || e.button !== 0 || e.target.closest('button,a,input,textarea,select,[role="button"]') || S.cw.wins.length < 2) return;
  const sec = h.parentElement, y0 = e.clientY;
  let on = false;
  const tgt = () => {  // the index the window would take: by the middle of the moved window among the others
    const r = sec.getBoundingClientRect(), mid = r.top + r.height / 2;
    return [...$('#achat').querySelectorAll('.cwin')].filter(s => s !== sec).filter(s => { const q = s.getBoundingClientRect(); return q.top + q.height / 2 < mid; }).length;
  };
  const mv = ev => {
    const dy = ev.clientY - y0;
    if (!on && Math.abs(dy) < 6) return;
    if (!on) { on = true; sec.classList.add('cwdrag'); }
    sec.style.transform = `translateY(${dy}px)`;
  };
  const up = () => {
    removeEventListener('pointermove', mv); removeEventListener('pointerup', up); removeEventListener('pointercancel', up);
    if (!on) return;
    const k = sec.dataset.cw, W = S.cw.wins, i = W.findIndex(w => w.k === k), j = tgt();
    sec.style.transform = ''; sec.classList.remove('cwdrag');
    if (j !== i) { const [w] = W.splice(i, 1); W.splice(j, 0, w); cw_save(); cw_draw(); }
  };
  addEventListener('pointermove', mv); addEventListener('pointerup', up); addEventListener('pointercancel', up);
});
window.addEventListener('resize', () => { if (!S.cw.wins.length || !cw_docked()) return; clearTimeout(cw_resT); cw_resT = setTimeout(() => { cw_fit(S.cw.act); cw_layout(); }, 150); });
let cw_resT = 0;

// ---- the header buttons, the X of an agent window, "Open in split window" (context menu, Ctrl / Cmd + click)
document.addEventListener('click', e => {
  const b = e.target.closest?.('#achat.cwsplit [data-cwact], #achat.cwsplit .cwin [data-act="chat-close"]');
  if (b) {
    const k = b.closest('.cwin')?.dataset.cw; if (!k) return;
    e.preventDefault(); e.stopPropagation();
    const a = b.dataset.cwact || 'close';
    if (a === 'fold') cw_fold(k); else if (a === 'menu') cw_menu(b, k); else cw_close(k);
    return;
  }
  const s = e.target.closest?.('.cwsw [data-cwsw]');  // the phone's row of open chats
  if (s) {
    e.preventDefault(); e.stopPropagation();
    const k = s.dataset.cwsw;
    if (s.dataset.rm) {  // 2.58.0 (#1771): the X at the active chat switches to the next open chat at once (the last one: closes it)
      const i = S.cw.wins.findIndex(w => w.k === k); S.cw.wins = S.cw.wins.filter(w => w.k !== k); delete S.cw.st[k];
      const nx = S.cw.wins[Math.max(0, i)] || S.cw.wins[i - 1]; S.cw.act = nx?.k || ''; cw_save();
      if (nx) go((nx.k[0] === 'a' ? 'agents/' : 'team/') + cw_id(nx.k)); else if (k[0] === 'a') chatClose(); else go('team');
      return;
    }
    S.cw.act = k; cw_save(); go((k[0] === 'a' ? 'agents/' : 'team/') + cw_id(k));
    return;
  }
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return;
  const k = cw_target(e.target); if (!k) return;
  e.preventDefault(); e.stopPropagation(); cw_split(k);
}, true);
// the chat a row / button opens: an agent ("Chat", the sidebar's agents, the agents' cards) or a conversation
function cw_target(el) {
  const a = el.closest?.('[data-act="chat-open"][data-aid], [data-act="team-agent"][data-aid], #view .tcrow[data-rid], #side .sbconv[data-go^="team/"]'); if (!a) return '';
  if (a.dataset.aid) return agentById(+a.dataset.aid)?.enabled ? 'a:' + +a.dataset.aid : '';
  const rid = +(a.dataset.rid || a.dataset.go.split('/')[1]); return rid ? 't:' + rid : '';
}
document.addEventListener('contextmenu', e => {
  if (e.shiftKey || !feat('agents') && !teamOn()) return;
  const el = e.target.closest?.('[data-act="chat-open"][data-aid], [data-act="team-agent"][data-aid], #view .tcrow[data-rid], #side .sbconv[data-go^="team/"]'), k = el && cw_target(el); if (!k) return;
  e.preventDefault();
  menu(el, [{label: tr('Open'), icon: 'comment', fn: () => el.click()}, {label: tr('Open in split window'), icon: 'panel', keys: IS_MAC ? 'Cmd+Click' : 'Ctrl+Click', fn: () => cw_split(k)},
    ...(el.closest('#side .srow') ? fv2_menuRow(fv2_rowKey(el)) : [])]);  // 2.57.0 (#1798): an agent in the sidebar can be a favourite
});

// ---- phones / tablets: no split; the open chats as a row of buttons above the chat (chatViewHtml, tcRoomHtml ask)
function cw_switchHtml(k) {
  if (!chatFull() || cw_ren) return '';
  const ks = S.cw.wins.map(w => w.k); if (!ks.includes(k)) ks.push(k);
  if (ks.length < 2) return '';
  return `<nav class="cwsw" aria-label="${esc(tr('Open chats'))}">${ks.map(x => {
    const on = x === k, n = cw_name(x) || '?', ico = x[0] === 'a' ? av(cw_id(x), n, 'avatar sm') : (() => { const r = (S.tc.rooms || []).find(y => y.id === cw_id(x)); return r ? roomIcon(r) : ic('users', 's'); })();
    return `<button type="button" class="cwswb${on ? ' on' : ''}" data-cwsw="${x}" ${on ? 'aria-current="true"' : ''}>${ico}<span>${esc(n)}</span>${!on && cw_unread(x) ? `<span class="cwdot" aria-label="${esc(tr('Unread messages'))}"></span>` : ''}</button>`
      + (on && cw_has(x) ? `<button type="button" class="iconbtn cwswx" data-cwsw="${x}" data-rm="1" title="${esc(tr('Remove from the open chats'))}" aria-label="${esc(tr('Remove from the open chats'))}">${ic('x', 's')}</button>` : '');
  }).join('')}</nav>`;
}
// the row above the chat on the page drawn already (the chat page only patches itself when drawn again)
function cw_swSync() {
  const v = $('#view .chview[data-aid]'), t = !v && S.route.mod === 'team' && S.tc.rid && $('#view .tcroom:not(.tcnone)');
  const box = v || t; if (!box) return;
  const h = cw_switchHtml(v ? 'a:' + v.dataset.aid : 't:' + S.tc.rid), old = $(':scope > .cwsw', box);
  if (old) { if (h) old.outerHTML = h; else old.remove(); }
  else if (h) box.insertAdjacentHTML('afterbegin', h);
}
