/* Kalmido web client: Team chat and notes of a list / project.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ #419 team chat
// Direct messages between two people (who share a list or a group) and one channel per shared list (agents of the list
// take part: they read it and answer when someone @mentions them). #team = the conversations, #team/<id> = one of them.
// Desktop: the list of conversations next to the open one; phones: the list, then the conversation full screen.
S.tc = {rooms: null, people: [], users: {}, avatars: {}, rid: null, room: null, msgs: [], more: false, loading: false, edit: null, err: null};
const teamOn = () => collab() && !!S.team?.enabled;
async function loadTeam() {
  if (!teamOn()) return;
  try {
    const j = await rawFetch('GET', '/api/team');
    Object.assign(S.tc, {rooms: j.rooms, people: j.people, users: {...S.tc.users, ...j.users}, err: null});
    if (j.avatars) S.avatars = {...(S.avatars || {}), ...j.avatars};
    if (S.team) S.team.unread = j.unread;
  } catch (e) { S.tc.err = e instanceof Offline ? tr('The team chat is only available online.') : e.message; }
}
async function loadRoom(rid, older = false) {
  if (!rid) return;
  const before = older && S.tc.msgs.length ? S.tc.msgs[0].id : null;
  let j;
  try { j = await rawFetch('GET', `/api/team/rooms/${rid}/messages` + (before ? `?before=${before}` : '')); }
  catch (e) { S.tc.err = e instanceof Offline ? tr('The team chat is only available online.') : e.message; return; }
  if (S.tc.rid !== rid) return;
  S.tc.room = j.room; S.tc.users = {...S.tc.users, ...j.users}; S.tc.more = j.has_more; S.tc.err = null;
  S.tc.pins = j.pins || [];  // 2.62.0 (#1848)
  S.tc.msgs = before ? [...j.messages, ...S.tc.msgs] : j.messages;
  e2eFromCache(S.tc.msgs); e2eRoomDecrypt(rid);  // 2.42.0 (#909): encrypted DMs (e2e.js)
  le2eChanDecrypt(rid);  // 2.64.2 (#1817): the channel of a list with the lock (liste2echan.js)
  const last = S.tc.msgs[S.tc.msgs.length - 1];
  if (last && (!j.room.last_read || last.id > j.room.last_read) && !document.hidden) {
    try { const r = await rawFetch('POST', `/api/team/rooms/${rid}/read`, {last_id: last.id}); if (S.team) S.team.unread = r.unread; } catch { /* offline */ }
    const rr = (S.tc.rooms || []).find(x => x.id === rid); if (rr) { rr.unread = 0; rr.mention = false; }
    wpSweep(tag => tag === 'team-' + rid);  // 2.19.0 (#668): the conversation's notifications close here
    renderSide(); renderTabs();
  }
}
// /api/version "t" moved: someone wrote / read somewhere -> the list and the open conversation again (no full reload)
async function teamChanged() {
  if (!teamOn()) return;
  await loadTeam();
  if (S.route.mod === 'team' && S.tc.rid) await loadRoom(S.tc.rid);
  if (S.route.mod === 'team' && !editingTeam()) renderView();
  else if (S.route.mod === 'team') tcPatch();
  if (typeof cw_teamLive === 'function') cw_teamLive();  // 2.47.1 (#1720): the team chats in the chat panel
  renderSide(); renderTabs(); renderTop();
}
// 2.18.0 (review): a one-line preview without Markdown markers ("```js", `code`, **bold**, headings, list markers, links ->
// their text); the server does the same in md_brief() (kalmido/collab/teamchat.py), this cleans the preview of a message sent from here
function mdBrief(t) {
  t = String(t || '').split('\n').map(l => l.replace(/^\s*(```|~~~)[\w+#.-]*\s*/, '').replace(/^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+[.)]\s+)/, '')).join('\n');
  t = t.replace(/!?\[([^\]]*)\]\([^)\s]*\)/g, '$1').replace(/\*\*|__|~~|`/g, '');
  return t.replace(/(^|[^\w*])\*(?=\S)([^*\n]+?)\*(?!\w)/g, '$1$2').replace(/\s+/g, ' ').trim();
}
const editingTeam = () => document.activeElement?.id === 'tc-in' || document.activeElement?.id === 'ms-q' || document.activeElement?.classList?.contains('tc-edit');
const roomName = r => r ? (r.kind === 'dm' ? (r.name || '?') : lname(listById(r.list_id)) || r.name || '?') : '';
const roomIcon = r => r.kind === 'dm' ? av(r.user_id, r.name, 'avatar') : tcx_isX(r) ? tcx_icon(r) : `<span class="tcico">${licon(listById(r.list_id), 'licon') || ic('users', 's')}</span>`;
function viewTeam() {
  if (typeof cw_tcHome === 'function' && S.cw.lt) return cw_tcHome(viewTeam);  // 2.47.1 (#1720): a conversation live in the chat panel (chatwins.js)
  if (!teamOn()) return `<div class="empty">${tr('The team chat needs collaboration (Settings > Modules).')}</div>`;
  if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.route.mod === 'team') renderView(); }); }
  // 2.27.0 (#986): only conversations that have messages (newest first); an empty one shows once it is opened / written in
  const rid = S.tc.rid, rooms = (S.tc.rooms || []).filter(r => (r.last || r.id === rid || tcx_isX(r)) && (r.kind === 'dm' || r.id === rid || (tcx_isX(r) ? tcx_vis(r) : inWs(listById(r.list_id)))));  // 2.28.0 (#935); 2.113.1 (#2059): channels / groups also without messages
  const list = `<nav class="tclist" aria-label="${esc(tr('Conversations'))}">
    <div class="tchead"><b>${tr('Conversations')}</b><span class="spacer"></span><button type="button" class="btn sm pri" data-act="tc-new" aria-haspopup="${S.tc.people.length ? 'menu' : 'dialog'}">${ic('plus', 's')}${tr('New message')}</button></div>
    ${S.tc.rooms === null ? `<div class="muted mhint">${tr('Loading…')}</div>` : rooms.length ? tcx_listHtml(rooms, r => `<button type="button" class="tcrow ${r.id === rid ? 'on' : ''} ${r.unread ? 'unread' : ''}" data-act="tc-open" data-rid="${r.id}" ${r.id === rid ? 'aria-current="true"' : ''}>
      ${roomIcon(r)}<span class="tcmain"><span class="tcn">${esc(roomName(r))}${r.kind !== 'dm' ? `<span class="tck">${ic('users', 's')}${r.members}</span>` : ''}</span>
      <span class="tclast">${r.last ? esc((r.last.user_id === S.me?.id ? tr('You') + ': ' : r.kind !== 'dm' ? uname(r.last.user_id, S.tc.users) + ': ' : '') + (e2eBriefText(r.last) ?? mdBrief(r.last.text))) : `<span class="muted">${tr('No messages yet')}</span>`}</span></span>
      <span class="tcside">${r.last_at ? `<time>${esc(relTime(r.last_at))}</time>` : ''}${r.unread ? `<span class="nbadge ${r.mention ? 'ment' : ''}" aria-label="${esc(trn('{0} unread', '{0} unread', r.unread))}">${r.mention ? '@' : ''}${r.unread}</span>` : ''}${r.muted ? `<span class="tcmute" title="${esc(tr('Muted'))}">${ic('belloff', 's')}</span>` : ''}</span></button>`)
    : `<div class="empty tcempty">${botFig('ruhig')}<b>${tr('No conversations yet')}</b><span>${S.tc.people.length || (S.tc.rooms || []).length ? tr('Write to someone you work with, or share a list: every shared list gets its own chat.') : tr('Share a list with someone: every shared list gets its own chat.')}</span>${S.tc.people.length || (S.tc.rooms || []).length ? `<button type="button" class="btn sm pri" data-act="tc-new">${ic('plus', 's')}${tr('Start a conversation')}</button>` : ''}</div>`}
  </nav>`;
  return `<div class="tcwrap"><div class="tcview ${rid ? 'inroom' : ''}">${list}${rid ? `<section class="tcroom" aria-label="${esc(roomName(S.tc.room ? {...S.tc.room, name: (rooms.find(x => x.id === rid) || {}).name} : rooms.find(x => x.id === rid)))}">${tcRoomHtml()}</section>` : (isMobile() ? '' : `<section class="tcroom tcnone"><div class="empty">${ic('comment')}<span>${tr('Pick a conversation.')}</span></div></section>`)}</div></div>`;
}
// 2.83.0 (#1774): "Open in split window" in the head of a team room (a phone has no long press / right click); not inside the panel itself
function o3b_splitBtn(room, rid) {
  if (!rid || room?.kind !== 'list' || typeof cw_split !== 'function' || (typeof cw_ren !== 'undefined' && cw_ren === 't:' + rid)) return '';
  return `<button type="button" class="iconbtn" data-act="tc-split" data-rid="${+rid}" title="${esc(tr('Open in split window'))}" aria-label="${esc(tr('Open in split window'))}">${ic('panel', 's')}</button>`;
}
function tcRoomHtml() {
  const rid = S.tc.rid, r = (S.tc.rooms || []).find(x => x.id === rid), room = S.tc.room;
  const name = roomName(r || room);
  const head = `<div class="tcrhead"><button type="button" class="iconbtn tcback" data-act="tc-back" aria-label="${esc(tr('Back'))}">${ic('back')}</button>
    ${r ? roomIcon(r) : ''}<div class="tcrt"><b>${esc(name)}</b>${room && room.kind !== 'dm' ? `<span class="muted">${esc(room.members.map(m => m.name).slice(0, 6).join(', '))}${room.members.length > 6 ? ' +' + (room.members.length - 6) : ''}</span>` : ''}</div>
    <span class="spacer"></span>${msgSearchBtn('t', rid)}${room && room.kind === 'list' ? `<button type="button" class="iconbtn" data-act="tc-list" data-id="${room.list_id}" title="${esc(tr('Open the list'))}" aria-label="${esc(tr('Open the list'))}">${ic('list')}</button>` : ''}
    ${typeof dw_winBtn === 'function' ? dw_winBtn('team', rid) : ''}${o3b_splitBtn(room, rid)}${tcx_headBtn(room)}${e2eRoomBtns(room)}<button type="button" class="iconbtn ${room?.muted ? 'on' : ''}" data-act="tc-mute" aria-pressed="${!!room?.muted}" title="${esc(room?.muted ? tr('Muted: only mentions notify you') : tr('Mute (only mentions notify you)'))}" aria-label="${esc(tr('Mute'))}">${ic(room?.muted ? 'belloff' : 'bell')}</button>${typeof cw_headBtns === 'function' ? cw_headBtns('t:' + rid) : ''}</div>`;
  return `${typeof cw_switchHtml === 'function' ? cw_switchHtml('t:' + rid) : ''}${head}${e2eRoomNotice(room)}${le2eChanNotice(room)}${cpnBarHtml('t:' + rid)}${msBarHtml('t', rid)}<div class="chmsgs tcmsgs" id="tc-msgs" role="log" aria-live="polite" aria-relevant="additions" aria-label="${esc(tr('Messages'))}">${tcMsgsHtml()}</div>
    <button type="button" class="chnew hidden" id="tc-new">${tr('New message')} <span aria-hidden="true">↓</span></button>
    ${room?.archived ? tcx_archivedHtml(room) : `${replyBarHtml('t:' + rid)}${tcx_filesBarHtml(room, rid)}<div class="chcomp tccomp">${tcx_clipHtml(room)}<div class="mpick hidden" role="listbox" aria-label="${esc(tr('Mention someone'))}"></div><textarea id="tc-in" rows="1" name="kalmido-team-message" autocomplete="off" data-form-type="other" data-lpignore="true" placeholder="${esc(tr('Message to {0}…', name.length > 18 ? name.slice(0, 17).trimEnd() + '…' : name))}" aria-label="${esc(tr('Message to {0}…', name))}" enterkeyhint="enter" maxlength="8000">${esc(S.drafts['team:' + rid] || '')}</textarea>
    <span class="muted chkh">${esc(chatKeyHintVis())}</span><button type="button" class="btn pri" data-act="tc-send" title="${esc(chatKeyHint())}"${csdBusy('t:' + rid) ? ' disabled' : ''}>${ic('send', 's')}<span>${tr('Send')}</span></button></div>`}`;
}
function tcMsgsHtml() {
  if (S.tc.err && !S.tc.msgs.length) return `<div class="muted mhint" data-k="err">${esc(S.tc.err)}</div>`;
  if (!S.tc.room) return `<div class="muted mhint" data-k="ld">${tr('Loading…')}</div>`;
  if (!S.tc.msgs.length && !csdBusy('t:' + S.tc.rid)) return `<div class="muted cmempty" data-k="empty">${tr('No messages yet. Say hello.')}</div>`;
  const U = S.tc.users, ags = new Set((S.tc.room.members || []).filter(m => m.agent).map(m => m.id));
  let prev = null, h = S.tc.more ? `<div class="chold" data-k="older"><button type="button" class="btn sm" data-act="tc-older">${tr('Load older messages')}</button></div>` : '';
  for (const m of S.tc.msgs) {
    const mine = m.user_id === S.me?.id, first = !prev || prev.user_id !== m.user_id || Date.parse(m.created_at) - Date.parse(prev.created_at) > 10 * 60000;
    prev = m;
    const rxr = rxRow(m.reactions || [], {mid: m.id, act: 'tc-react', dis: !!m.deleted || S.tc.edit === m.id, own: mine, key: 't' + m.id});  // 2.18.0 (#651), 2.23.0 (#823)
    const eb = m.deleted ? null : e2eMsgBody(m);  // 2.42.0 (#909): a notice / an encrypted message not decrypted (yet)
    const lb = eb && !m.enc.sys && le2eChanOn(S.tc.room) ? le2eChanMsgBody(m) : eb;  // 2.64.2 (#1817): unlock = the list's key
    if (eb && m.enc.sys) { h += `<div class="cmsg sys" data-k="m${m.id}" data-mid="t:${m.id}">${eb}</div>`; prev = null; continue; }
    const body = m.deleted ? `<div class="cbub del"><span class="muted">${tr('Message deleted')}</span></div>` : lb ? lb
      : S.tc.edit === m.id ? `<div class="cbub tcedit"><div class="mpick hidden" role="listbox" aria-label="${esc(tr('Mention someone'))}"></div><textarea class="tc-edit" enterkeyhint="enter" aria-label="${esc(tr('Edit message'))}" rows="2">${esc(m.body.replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, U)))}</textarea><div class="tcebtn"><button type="button" class="btn sm" data-act="tc-edit-cancel">${tr('Cancel')}</button><button type="button" class="btn sm pri" data-act="tc-edit-save" data-mid="${m.id}">${tr('Save')}</button></div></div>`
        : `${replyQuoteHtml(m, 't')}${m.body || !m.attachments?.length ? `<div class="cbub">${commentBody(m.body, U)}</div>` : ''}${tcx_attHtml(m)}`;  // 2.33.0 (#1076): the quote of the answered message; 2.113.1 (#2059): + files
    h += `<div class="cmsg ${mine ? 'me' : 'ag'}${!mine && ags.has(m.user_id) ? ' agc' : ''} ${first ? 'first' : ''}${rxShow('t' + m.id)}" data-k="m${m.id}" data-mid="t:${m.id}">
      ${first && !mine ? `<div class="tcwho">${av(m.user_id, uname(m.user_id, U), 'avatar sm')}<b>${esc(uname(m.user_id, U))}</b>${ags.has(m.user_id) ? agentBadge() : ''}</div>` : ''}
      ${body}${m.task ? `<button class="runtask" data-act="open-id" data-id="${m.task.id}">${ic('arrow', 's')}<span>${esc(m.task.title)}</span></button>` : ''}
      <div class="cmeta"><time title="${esc(fmtWhen(m.created_at))}">${fmtWhen(m.created_at)}</time>${m.edited_at && !m.deleted ? `<span class="muted">${tr('edited')}</span>` : ''}${cpnMark(m)}${rxr}${m.deleted || S.tc.edit === m.id ? '' : replyBtn('chrbtn mreply')}${m.deleted ? '' : chatSavedMark(m)}${!m.deleted ? `<button type="button" class="rx rxtog" data-act="tc-msg-menu" data-mid="${m.id}" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button>` : ''}</div></div>`;
  }
  return h + csdHtml('t:' + S.tc.rid, S.tc.msgs, m => m.user_id === S.me?.id);  // 2.62.0 (#1530): "Sending…"
}
// patch the open conversation in place (keeps the box, its text and the keyboard)
function tcPatch(bottom) {
  const box = $('#tc-msgs'); if (!box) return;
  const near = bottom || box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  setHtml(box, tcMsgsHtml());
  const added = cf_after(box, 't:' + S.tc.rid);  // 2.46.2 (#1660): new messages fade in; scrolled up -> "New message ↓"
  if (near) { box.scrollTop = box.scrollHeight; cf_pill('tc-new', false); }
  else if (added.length) cf_pill('tc-new', true);
  cpnSync();  // 2.62.0 (#1848): the bar of pinned messages
}
// a tap, the wheel or a key in the log ends the "stay at the newest message" phase (the person reads / reacts)
for (const ev of ['pointerdown', 'wheel', 'touchstart', 'keydown']) document.addEventListener(ev, e => { if (S.tc?.fitUntil && e.target.closest?.('#tc-msgs')) S.tc.fitUntil = 0; }, {capture: true, passive: true});
function teamFit(again) {
  const box = $('#tc-msgs'); if (box) box.scrollTop = box.scrollHeight;
  if (again) return;
  // the first load of a page (state, fonts, avatars) re-renders and grows the log after this: stay at the end for a moment
  S.tc.fitUntil = Date.now() + 2000;
  for (const ms of [60, 300, 900]) setTimeout(() => { if (document && S.route.mod === 'team' && S.tc.fitUntil > Date.now()) teamFit(true); }, ms);
}
// "@Name" of a member -> <@id> (longest names first), so the server can tell the person
function tcMentions(text) {
  const mem = (S.tc.room?.members || []).filter(m => m.id !== S.me?.id).sort((a, b) => b.name.length - a.name.length);
  for (const m of mem) text = text.replace(new RegExp(`(^|[^\\p{L}\\p{N}_@])@${m.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}\\p{N}_])`, 'giu'), `$1<@${m.id}>`);
  return text;
}
async function tcSend() {
  const ta = $('#tc-in'), rid = S.tc.rid; if (!ta || !rid) return;
  const text = ta.value.trim(), files = tcx_filesOk(S.tc.room) ? S.tc.files[rid] || [] : []; if (!text && !files.length) return;  // 2.113.1 (#2059): + files
  const hadF = document.activeElement === ta, ck = 't:' + rid; if (csdBusy(ck)) return;  // 2.62.0 (#1530): one send at a time
  const p = csdAdd(ck, text, S.tc.msgs), sb = () => $('[data-act="tc-send"]');  // shown as "Sending…", the box empties at once
  ta.value = ''; delete S.drafts['team:' + rid]; autosize(ta); if (sb()) sb().disabled = true; tcPatch(true);
  if (!S.tc.room) { try { await loadRoom(rid); } catch { /* sent without the mention lookup */ } }  // 2.24.0: @names need the members
  let m; const msgs = S.tc.msgs;  // 2.58.0 (#1773): another window may become live during the POST (like chatSend)
  const rto = replyTo('t:' + rid);  // 2.33.0 (#1076)
  try {
    // 2.42.0 (#909): an encrypted DM sends only the ciphertext (encrypted in this browser)
    // 2.64.2 (#1817): the channel of a list with the lock: the text with its mention tokens, encrypted with the list key
    const lk = le2eChanOn(S.tc.room), ltext = lk ? tcMentions(text) : null;
    const enc = lk ? await le2eChanEnc(S.tc.room, ltext) : S.tc.room?.e2e ? await e2eDmEncrypt(rid, text) : null; if ((lk || S.tc.room?.e2e) && !enc) throw null;  // 2.62.0 (#1530): throw = the text goes back into the box
    if (!enc && !await e2eDownOk(rid)) throw null;  // 2.42.0 (#909): switched off by the server alone -> ask first
    m = await rawFetch('POST', `/api/team/rooms/${rid}/messages`, files.length && !enc ? tcx_form(tcMentions(text), rto, p.cid, files) : {...(enc ? {enc} : {body: tcMentions(text)}), ...(lk ? {mentions: le2eChanMentions(ltext)} : {}), ...(rto ? {reply_to: rto} : {}), client_id: p.cid});
    if (enc) { m.body = lk ? ltext : text; m._dec = true; E2E.dec[m.id + ':'] = m.body; }
  }
  catch (e) {  // 2.62.0 (#1530): the text goes back into the box
    csdDone(ck, p); csdBack($('#tc-in'), text, 'team:' + rid); if (sb()) sb().disabled = false; tcPatch();
    if (e) toast(e instanceof Offline ? tr('You are offline: the message was not sent and stays in the box') : e.message); return;
  }
  csdDone(ck, p); if (sb()) sb().disabled = false; replySent('t:' + rid);
  if (files.length) { delete S.tc.files[rid]; tcx_chipsSync(); }
  const live = S.tc.rid === rid, k = 't:' + rid, arr = live ? S.tc.msgs : S.cw?.home?.rid === rid ? S.cw.home.msgs : typeof cw_has === 'function' && cw_has(k) ? cw_stOf(k).msgs : msgs;
  if (arr && !arr.some(x => x.id === m.id)) arr.push(m);
  const r = (S.tc.rooms || []).find(x => x.id === rid); if (r) { r.last = {id: m.id, user_id: m.user_id, text: text || files[0]?.name || '', created_at: m.created_at}; r.last_at = m.created_at; }
  if (!live) { if (typeof cw_has === 'function' && cw_has(k)) cw_patch(k); return; }
  tcPatch(true);
  if (hadF || !isTouch()) ta.focus({preventScroll: true});
}
async function tcReact(mid, emoji) {
  let r; try { r = await rawFetch('POST', `/api/team/messages/${mid}/reactions`, {emoji}); } catch (e) { toast(e.message); return; }
  const m = S.tc.msgs.find(x => x.id === mid); if (m) m.reactions = r.reactions;
  tcPatch(); rxRefocus('#tc-msgs', mid, emoji);
}
function tcMsgMenu(anchor, mid) {
  const m = S.tc.msgs.find(x => x.id === mid); if (!m || m.deleted) return;
  const mine = m.user_id === S.me?.id;  // 2.37.0 (#1159): the menu on every message (Save as task); Edit / Delete only on my own
  menu(anchor, [{label: tr('Reply'), icon: 'reply', fn: () => replyStart('t', mid)}, cpnItem('t', m),  // 2.62.0 (#1848): Pin / Unpin
    {label: tr('Copy'), icon: 'copy', fn: () => chatCopy(S.tc.msgs, m, 'team')},  // 2.37.0 (#1165)
    {label: tr('Copy as Markdown'), icon: 'copy', fn: () => chatCopy(S.tc.msgs, m, 'team', true)},  // 2.41.0 (#1374)
    ...(m.enc ? [] : [{label: m.saved_task_id ? tr('Saved as a task: open it') : tr('Save as task'), icon: 'bookmark', fn: () => m.saved_task_id ? chatSaveOpen(m.saved_task_id) : chatSaveModal('team', m, () => tcPatch())}]),  // 2.42.0 (#909): not for encrypted ones
    ...(mine && !(m.enc && !m._dec) ? [{label: tr('Edit'), icon: 'edit', fn: () => { S.tc.edit = mid; tcPatch(); setTimeout(() => { const t = $('#tc-msgs .tc-edit'); if (t) { t.focus(); autosize(t); } }, 0); }},
      {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => tcMsgDelete(mid)}] : [])]);
}
async function tcMsgDelete(mid) {
  const m = S.tc.msgs.find(x => x.id === mid); if (!m) return false;
  if (!await askConfirm(tr('Delete this message?'), '', {ok: tr('Delete'), danger: true})) return false;
  try { await rawFetch('DELETE', `/api/team/messages/${mid}`); } catch (e) { toast(e.message); return false; }
  if (S.tc.edit === mid) S.tc.edit = null;
  Object.assign(m, {deleted: true, body: '', reactions: []}); tcPatch(); announce(tr('Message deleted'));
  return true;
}
async function tcEditSave(mid) {
  const t = $('#tc-msgs .tc-edit'), m = S.tc.msgs.find(x => x.id === mid); if (!t || !m) return;
  const v = t.value.trim();
  // 2.18.0 (#652): saving an emptied message did nothing; it offers to delete the message instead (Cancel: back to the
  // text box, Delete: the focus goes to the message box); 2.113.1 (#2059): a message with files keeps them without text
  if (!v && !m.attachments?.length) { if (await tcMsgDelete(mid)) $('#tc-in')?.focus(); else $('#tc-msgs .tc-edit')?.focus(); return; }
  let r;
  try {
    const lk = le2eChanOn(S.tc.room), lv = lk ? tcMentions(v) : null;  // 2.64.2 (#1817): the list key, the current generation
    const enc = lk ? await le2eChanEnc(S.tc.room, lv) : m.enc ? await e2eDmEncrypt(S.tc.rid, v) : null; if ((lk || m.enc) && !enc) return;  // 2.42.0 (#909): encrypted again
    r = await rawFetch('PATCH', `/api/team/messages/${mid}`, enc ? {enc} : {body: tcMentions(v)});
    if (enc) { r.body = lk ? lv : v; r._dec = true; E2E.dec[r.id + ':' + (r.edited_at || '')] = r.body; }
  } catch (e) { toast(e.message); return; }
  Object.assign(m, r); S.tc.edit = null; tcPatch();
}
async function tcMute() {
  const rid = S.tc.rid, on = !S.tc.room?.muted;
  try { await rawFetch('POST', `/api/team/rooms/${rid}/read`, {muted: on}); } catch (e) { toast(e.message); return; }
  S.tc.room.muted = on; const r = (S.tc.rooms || []).find(x => x.id === rid); if (r) r.muted = on;
  toast(on ? tr('Muted: only mentions notify you') : tr('Notifications on')); renderView();
}
function tcNewMenu(anchor) {
  // 2.27.0 (#986): people (a direct message) and the chats of shared lists nobody has written in yet
  const quiet = (S.tc.rooms || []).filter(r => r.kind === 'list' && !r.last).sort((a, b) => roomName(a).localeCompare(roomName(b), LOCALE()));
  // 2.113.1 (#2059): a channel, a group, the open channels to join
  const xs = [{label: tr('New channel'), icon: 'hash', fn: tcx_chanNew}, ...(S.tc.people.length >= 2 ? [{label: tr('New group'), icon: 'users', fn: tcx_groupNew}] : []), {label: tr('Browse channels'), icon: 'search', fn: tcx_browse}, '-'];
  if (!S.tc.people.length && !quiet.length) { menu(anchor, [...xs.slice(0, -1), '-', {label: tr('Direct messages'), icon: 'user', fn: () => dmWhy()}]); return; }  // 2.24.0 (#906): explains why no DM yet
  menu(anchor, [...xs, ...S.tc.people.map(p => ({label: p.name, icon: 'user', fn: () => dmOpen(p.id, p.name)})),
    ...(quiet.length ? [...(S.tc.people.length ? ['-'] : []), ...quiet.map(r => ({label: roomName(r), icon: 'users', fn: () => go('team/' + r.id)}))] : [])]);
}
// 2.24.0 (#906): a direct message from anywhere (the person card, "Tasks of …", the team chat). When it cannot work yet the
// button still shows and says why (team chat off, nobody to write to, or the server's reason).
async function dmOpen(uid, name) {
  if (!teamOn()) { dmWhy('off'); return; }
  let r; try { r = await rawFetch('POST', '/api/team/dm', {user_id: uid}); } catch (e) { dmWhy('err', e.message, name); return; }
  if (!(S.tc.rooms || []).some(x => x.id === r.id)) S.tc.rooms = [{...r, unread: 0, mention: false, muted: false, last: null, last_at: null}, ...(S.tc.rooms || [])];
  go('team/' + r.id);
}
async function dmWhy(kind, msg, name) {
  const off = kind === 'off' || !teamOn();
  const html = `<p>${off ? tr('Direct messages are part of the team chat. Switch on collaboration in Settings > Modules > Collaboration.')
      : kind === 'err' ? esc(tr('You cannot write to {0} yet.', name || tr('this person'))) + (msg ? ' <span class="muted">' + esc(msg) + '</span>' : '')
      : tr('Nobody to write to yet.')}</p>${off ? '' : `<p class="muted">${tr('You can write to people you share a list with (or who are in your organisation). Share a list with someone, or ask an admin to set up their account.')}</p>`}`;
  const ok = await askDialog({title: tr('Direct messages'), html, ok: off ? tr('Open Modules') : tr('OK'), cancel: tr('Close')});
  if (ok && off) settingsModal('collab');
}
// 2.94.0 (#2024): title of the Send buttons; no key hint on touch devices without a keyboard
// 2.102.0 B (#2204): the visible hint next to a send button; empty on touch devices (the tooltip text there is just "Send")
const chatKeyHintVis = () => matchMedia('(hover:none)').matches ? '' : chatKeyHint();
const chatKeyHint = () => matchMedia('(hover:none)').matches ? tr('Send') : /Mac|iPhone|iPad/.test(navigator.platform || '') ? tr('Cmd+Enter sends') : tr('Ctrl+Enter sends');
// the open conversation follows the route; switching rooms loads it
function teamRoute(rid) {
  if (typeof cw_route === 'function' && cw_route(rid)) return;  // 2.47.1 (#1720): the phone's row of open chats / a conversation live in the chat panel
  if (S.tc.rid !== rid) { S.tc.rid = rid; S.tc.room = null; S.tc.msgs = []; S.tc.more = false; S.tc.edit = null; if (rid) loadRoom(rid).then(() => { if (S.route.mod === 'team' && S.tc.rid === rid) { renderView(); teamFit(); } }); }
}
document.addEventListener('keydown', e => {
  if (e.target.id === 'tc-in' && e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing)  // 2.94.0 (#2024): Enter = new line, Ctrl/Cmd+Enter sends
    { e.preventDefault(); tcSend(); }
  if (e.key === 'Escape' && S.dash?.custom && e.target.closest?.('.dash')) { e.preventDefault(); e.stopPropagation(); $('#view [data-act="dash-done"]')?.click(); return; }  // 2.17.2
  if (e.target.classList?.contains('tc-edit')) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); tcEditSave(S.tc.edit); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); S.tc.edit = null; tcPatch(); setTimeout(() => { if (document) $('#tc-in')?.focus(); }, 0); }
  }
}, true);
document.addEventListener('input', e => { if (e.target.id === 'tc-in' || e.target.classList?.contains('tc-edit')) { if (e.target.id === 'tc-in') S.drafts['team:' + S.tc.rid] = e.target.value; autosize(e.target); mentionUpdate(e.target); } });
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="tc-"]'); if (!a) return;
  const act = a.dataset.act;
  if (act === 'tc-open') { go('team/' + a.dataset.rid); }
  else if (act === 'tc-back') go('team');
  else if (act === 'tc-send') tcSend();
  else if (act === 'tc-react') { tcReact(+a.dataset.mid, a.dataset.e); }
  else if (act === 'tc-older') loadRoom(S.tc.rid, true).then(() => tcPatch());
  else if (act === 'tc-msg-menu') tcMsgMenu(a, +a.dataset.mid);
  else if (act === 'tc-edit-save') tcEditSave(+a.dataset.mid);
  else if (act === 'tc-edit-cancel') { S.tc.edit = null; tcPatch(); }
  else if (act === 'tc-mute') tcMute();
  else if (act === 'tc-new') tcNewMenu(a);
  else if (act === 'tc-list') go('l/' + a.dataset.id);
  else if (act === 'tc-split') cw_split('t:' + +a.dataset.rid);  // 2.83.0 (#1774)
  else if (act === 'tc-attach') $('#tc-file')?.click();  // 2.113.1 (#2059)
  else if (act === 'tc-file-rm') { (S.tc.files[S.tc.rid] || []).splice(+a.dataset.i, 1); tcx_chipsSync(); $('#tc-in')?.focus(); }
  else if (act === 'tc-att-view') { const m = S.tc.msgs.find(x => x.id === +a.dataset.mid); attLightbox(+a.dataset.fid, (m?.attachments || []).filter(isImg)); }
  else if (act === 'tc-set') tcx_settings();
  else if (act === 'tc-restore') tcx_restore(+a.dataset.rid);
  else return;
  e.preventDefault(); e.stopPropagation();
});
// ------------------------------------------------------------------ 2.113.1 (#2059): channels, groups, files
// Channels anyone opens (for an organisation: open to all its people or invited only; or in the own space with people one
// works with), group conversations of three or more people, files in team chat messages (clip, paste, drag & drop).
// The server decides who may do what (kalmido/collab/teamchan.py); the app only offers it.
const tcx_isX = r => r?.kind === 'channel' || r?.kind === 'group';
const tcx_vis = r => !r.org_id || inWs({org_id: r.org_id});
const tcx_icon = r => `<span class="tcico">${ic(r.kind === 'channel' ? 'hash' : 'users', 's')}</span>`;
function tcx_listHtml(rooms, row) {
  const ch = rooms.filter(r => r.kind === 'channel'), gr = rooms.filter(r => r.kind === 'group'), rest = rooms.filter(r => !tcx_isX(r));
  if (!ch.length && !gr.length) return rest.map(row).join('');
  const sec = (t, a) => a.length ? `<div class="tcsec" role="heading" aria-level="3">${esc(t)}</div>${a.map(row).join('')}` : '';
  return sec(tr('Channels'), ch) + sec(tr('Groups'), gr) + sec(tr('Lists and direct messages'), rest);
}
const tcx_headBtn = room => tcx_isX(room) ? `<button type="button" class="iconbtn" data-act="tc-set" title="${esc(room.kind === 'channel' ? tr('Channel settings') : tr('Group settings'))}" aria-label="${esc(room.kind === 'channel' ? tr('Channel settings') : tr('Group settings'))}">${ic('gear')}</button>` : '';
const tcx_archivedHtml = room => `<div class="tcarch" role="status">${ic('archive', 's')}<span>${tr('This channel is archived')}</span>${room.manage ? `<button type="button" class="btn sm" data-act="tc-restore" data-rid="${room.id}">${tr('Restore')}</button>` : ''}</div>`;
// files: what waits in the composer (per conversation), the clip, the message's files
S.tc.files = {};
const tcx_filesOk = room => !!room && !room.e2e && !(typeof le2eChanOn === 'function' && le2eChanOn(room)) && !room.archived;
const tcx_chipsHtml = rid => (S.tc.files[rid] || []).map((f, i) => `<span class="cfile">${ic(/^image\//.test(f.type) ? 'clip' : 'file', 's')}<span>${esc(f.name || tr('Image'))}</span><button type="button" data-act="tc-file-rm" data-i="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove') + ': ' + (f.name || tr('Image')))}">${ic('x', 's')}</button></span>`).join('');
const tcx_clipHtml = room => tcx_filesOk(room) ? `<button type="button" class="iconbtn chclip" data-act="tc-attach" title="${esc(tr('Attach images or files'))}" aria-label="${esc(tr('Attach images or files'))}">${ic('clip')}</button><input type="file" id="tc-file" multiple hidden>` : '';
const tcx_filesBarHtml = (room, rid) => tcx_filesOk(room) ? `<div class="cfiles tcfiles" id="tc-files">${tcx_chipsHtml(rid)}</div>` : '';
function tcx_chipsSync() { const b = $('#tc-files'); if (b) b.innerHTML = tcx_chipsHtml(S.tc.rid); }
function tcx_addFiles(files, rid = S.tc.rid) {
  if (!rid || !tcx_filesOk(S.tc.room)) { if (files?.length) toast(S.tc.room?.archived ? tr('This channel is archived') : tr('Files cannot be sent in an end-to-end encrypted conversation')); return; }
  files = noEmpty(files); if (!files.length) return;
  const big = files.find(f => f.size > 50 * 1024 * 1024);
  if (big) { toast(tr('{0} is larger than 50 MB', big.name)); files = files.filter(f => f !== big); }
  const arr = S.tc.files[rid] ||= [];
  arr.push(...files.slice(0, Math.max(0, 10 - arr.length)));
  if (arr.length >= 10 && files.length) toast(tr('At most {0} files per message', 10));
  tcx_chipsSync();
}
function tcx_form(body, rto, cid, files) {
  const fd = new FormData(); if (body) fd.append('body', body); if (rto) fd.append('reply_to', rto); if (cid) fd.append('client_id', cid);
  files.forEach((f, i) => fd.append('file', f, f.name || `bild-${Date.now()}-${i}.png`));
  return fd;
}
function tcx_attHtml(m) {
  const fs = m.deleted ? [] : m.attachments || []; if (!fs.length) return '';
  return `<div class="atts chatts">${fs.map(a => upLocked(a) ? scnLockedTile(a)
    : isImg(a) ? `<div class="att img"><a href="${attUrl(a)}" data-act="tc-att-view" data-mid="${m.id}" data-fid="${a.id}" title="${esc(a.name)}"><img src="${attUrl(a)}" loading="lazy" alt="${esc(a.name)}"></a>${scnImgMark(a)}</div>`
    : `<div class="att file">${attFileA(a)}</div>`).join('')}</div>`;
}
document.addEventListener('change', e => { if (e.target.id === 'tc-file') { tcx_addFiles(e.target.files); e.target.value = ''; $('#tc-in')?.focus(); } });
document.addEventListener('paste', e => {
  if (document.activeElement?.id !== 'tc-in') return;
  const f = [...(e.clipboardData?.files || [])]; if (!f.length) return;
  e.preventDefault(); e.stopImmediatePropagation(); tcx_addFiles(f);
}, true);
const tcx_dropZone = e => { const z = e.target.closest?.('#view .tcroom'); return z && S.tc.rid && tcx_filesOk(S.tc.room) ? z : null; };
document.addEventListener('dragover', e => { if (!hasFiles(e)) return; const z = tcx_dropZone(e); if (!z) return; e.preventDefault(); e.stopImmediatePropagation(); e.dataTransfer.dropEffect = 'copy'; z.classList.add('filedrop'); }, true);
document.addEventListener('dragleave', e => { if (hasFiles(e) && !e.relatedTarget?.closest?.('.tcroom')) $$('.tcroom.filedrop').forEach(x => x.classList.remove('filedrop')); }, true);
document.addEventListener('drop', e => {
  if (!hasFiles(e)) return; const z = tcx_dropZone(e); if (!z) return;
  e.preventDefault(); e.stopImmediatePropagation(); z.classList.remove('filedrop'); tcx_addFiles(e.dataTransfer.files); $('#tc-in')?.focus();
}, true);
// channels / groups: create, settings, browse
async function tcx_req(method, url, body) {
  try { return await rawFetch(method, url, body); } catch (e) { toast(e instanceof Offline ? tr('The team chat is only available online.') : e.message); return null; }
}
async function tcx_refresh(rid) { await loadTeam(); if (rid && S.tc.rid === rid) await loadRoom(rid); if (S.route.mod === 'team') renderView(); renderSide(); }
const tcx_pick = (ids, users, agents = [], on = []) => ids.length || agents.length ? `<div class="tcxpick" role="group" aria-label="${esc(tr('Members'))}">${[...ids.map(id => [id, false]), ...agents.map(id => [id, true])].map(([id, ag]) => `<label class="tcxp"><input type="checkbox" value="${id}" ${on.includes(id) ? 'checked' : ''}>${av(id, users[id] || '?', 'avatar sm')}<span>${esc(users[id] || '?')}</span>${ag ? agentBadge() : ''}</label>`).join('')}</div>` : `<p class="muted">${tr('Nobody to add yet.')}</p>`;
const tcx_checked = md => $$('.tcxpick input:checked', md).map(x => +x.value);
function tcx_dlg(title, inner, ok, wire) {
  return new Promise(res => {
    let done = false;
    const md = modal(`<form class="tcxdlg" novalidate><h3>${esc(title)}</h3>${inner}<div class="foot"><span class="spacer"></span><button type="button" class="btn" data-x="no">${tr('Cancel')}</button><button type="submit" class="btn pri">${esc(ok)}</button></div></form>`);
    modalA11y(md);
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); };
    md.querySelector('form').addEventListener('submit', e => { e.preventDefault(); const v = wire.submit(md); if (v) fin(v); });
    md.addEventListener('click', e => { if (e.target.closest('[data-x="no"]')) fin(null); });
    if (wire.init) wire.init(md);
    onRemove(md, () => fin(null));
    setTimeout(() => $('input[type="text"]', md)?.focus(), 30);
  });
}
async function tcx_chanNew() {
  const j = await tcx_req('GET', '/api/team/channels'); if (!j) return;
  const U = {...S.tc.users, ...j.users};
  const spaces = [...j.orgs.map(o => ({id: o.id, name: o.name, people: o.people, agents: o.agents})), {id: 0, name: tr('Private|workspace'), people: j.people, agents: j.agents}];
  const cur = spaces.find(s => s.id && wsCur() === 'org:' + s.id) || spaces[0];
  const sp = md => spaces.find(s => s.id === +($('#tcx-sp', md)?.value || 0)) || cur;
  const draw = md => { const s = sp(md), op = $('#tcx-open', md); op.disabled = !s.id; if (!s.id) op.checked = false; $('#tcx-mem', md).innerHTML = tcx_pick(s.people, U, s.agents); $('#tcx-oh', md).textContent = s.id ? tr('Everyone in {0} can find and join it.', s.name) : tr('Channels of your own space are for invited people only.'); };
  const v = await tcx_dlg(tr('New channel'), `<div class="row"><label for="tcx-name">${tr('Name')}</label><input type="text" id="tcx-name" maxlength="80" autocomplete="off" placeholder="${esc(tr('e.g. General'))}"></div>
    ${spaces.length > 1 ? `<div class="row"><label for="tcx-sp">${tr('Workspace')}</label><select id="tcx-sp">${spaces.map(s => `<option value="${s.id}" ${s === cur ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>` : ''}
    <div class="row"><label class="chkl"><input type="checkbox" id="tcx-open" ${cur.id ? 'checked' : ''}> ${tr('Open to the whole organisation')}</label></div><p class="muted tcxhint" id="tcx-oh"></p>
    <div class="tcxsec"><b>${tr('Invite')}</b><div id="tcx-mem"></div></div>`, tr('Create'), {
    init: md => { draw(md); $('#tcx-sp', md)?.addEventListener('change', () => draw(md)); },
    submit: md => { const name = $('#tcx-name', md).value.trim(); if (!name) { toast(tr('Give the channel a name')); $('#tcx-name', md).focus(); return null; }
      const s = sp(md); return {name, org_id: s.id || null, open: !!s.id && $('#tcx-open', md).checked, members: tcx_checked(md)}; }});
  if (!v) return;
  const r = await tcx_req('POST', '/api/team/channels', v); if (!r) return;
  offerUndo(tr('Channel “{0}” created', r.name), histAdd({label: tr('New channel “{0}”', r.name), undo: () => rawFetch('PATCH', `/api/team/rooms/${r.id}`, {archived: true}).then(() => tcx_refresh()), redo: () => rawFetch('PATCH', `/api/team/rooms/${r.id}`, {archived: false}).then(() => tcx_refresh())}));
  await loadTeam(); go('team/' + r.id);
}
async function tcx_groupNew() {
  const ppl = S.tc.people || [];
  if (ppl.length < 2) { dmWhy(); return; }
  const U = Object.fromEntries(ppl.map(p => [p.id, p.name]));
  const v = await tcx_dlg(tr('New group'), `<p class="muted tcxhint">${tr('A group conversation with at least two people you work with (everyone in it must work with each other).')}</p>
    <div class="tcxsec"><b>${tr('Members')}</b>${tcx_pick(ppl.map(p => p.id), U)}</div>
    <div class="row"><label for="tcx-name">${tr('Name (optional)')}</label><input type="text" id="tcx-name" maxlength="80" autocomplete="off"></div>`, tr('Create'), {
    submit: md => { const m = tcx_checked(md); if (m.length < 2) { toast(tr('A group needs at least two other people')); return null; } return {members: m, name: $('#tcx-name', md).value.trim()}; }});
  if (!v) return;
  const r = await tcx_req('POST', '/api/team/groups', v); if (!r) return;
  await loadTeam(); go('team/' + r.id);
}
async function tcx_browse() {
  const j = await tcx_req('GET', '/api/team/channels'); if (!j) return;
  const open = j.channels.filter(c => !c.joined && !c.archived && c.open), arch = j.channels.filter(c => c.archived && c.manage);
  const row = (c, act, lbl) => `<div class="tcxrow">${tcx_icon(c)}<span class="tcxn"><b>${esc(c.name)}</b><span class="muted">${esc(trn('{0} member', '{0} members', c.members))}</span></span><button type="button" class="btn sm" data-xb="${act}" data-rid="${c.id}">${lbl}</button></div>`;
  const md = modal(`<h3>${tr('Browse channels')}</h3>${open.length ? open.map(c => row(c, 'join', tr('Join'))).join('') : `<p class="muted">${tr('No open channels to join.')}</p>`}
    ${arch.length ? `<h4>${tr('Archived')}</h4>${arch.map(c => row(c, 'restore', tr('Restore'))).join('')}` : ''}<div class="foot"><span class="spacer"></span><button type="button" class="btn" data-xb="close">${tr('Close')}</button></div>`);
  modalA11y(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-xb]'); if (!b) return;
    if (b.dataset.xb === 'close') { md.remove(); return; }
    const rid = +b.dataset.rid; md.remove();
    if (b.dataset.xb === 'join') { if (await tcx_req('POST', `/api/team/rooms/${rid}/members`, {user_id: S.me.id})) { await loadTeam(); go('team/' + rid); } }
    else tcx_restore(rid);
  });
}
async function tcx_restore(rid) {
  if (!await tcx_req('PATCH', `/api/team/rooms/${rid}`, {archived: false})) return;
  offerUndo(tr('Channel restored'), histAdd({label: tr('Channel restored'), undo: () => rawFetch('PATCH', `/api/team/rooms/${rid}`, {archived: true}).then(() => tcx_refresh(rid)), redo: () => rawFetch('PATCH', `/api/team/rooms/${rid}`, {archived: false}).then(() => tcx_refresh(rid))}));
  await tcx_refresh(rid); go('team/' + rid);
}
// the settings of a channel / group: name, open, members, archive, leave (each change at once, one undo step each)
async function tcx_settings() {
  const rid = S.tc.rid, room = S.tc.room; if (!tcx_isX(room)) return;
  const ch = room.kind === 'channel', man = !!room.manage;
  let cand = null;
  if (man) { const j = await tcx_req('GET', '/api/team/channels'); if (!j) return; S.tc.users = {...S.tc.users, ...j.users};
    cand = ch ? (room.org_id ? (j.orgs.find(o => o.id === room.org_id) || {people: [], agents: []}) : {people: j.people, agents: j.agents}) : {people: j.people, agents: []}; }
  const md = modal('<div id="tcx-set"></div>');
  modalA11y(md);
  const step = (label, undo, redo) => offerUndo(label, histAdd({label, undo: () => undo().then(() => tcx_refresh(rid)), redo: () => redo().then(() => tcx_refresh(rid))}));
  const patch = b => rawFetch('PATCH', `/api/team/rooms/${rid}`, b);
  const draw = () => {
    const r = S.tc.room || room, mem = r.members || [], ids = new Set(mem.map(m => m.id));
    const add = man && cand ? [...cand.people, ...cand.agents].filter(id => !ids.has(id) && id !== S.me.id) : [];
    $('#tcx-set', md).innerHTML = `<h3>${esc(ch ? tr('Channel settings') : tr('Group settings'))}</h3>
      ${man ? `<form class="tcxname row"><label for="tcx-name">${tr('Name')}</label><input type="text" id="tcx-name" maxlength="80" value="${esc(r.kind === 'group' ? r.custom_name || '' : r.name || '')}" ${ch ? '' : `placeholder="${esc(r.name || '')}"`}><button type="submit" class="btn sm">${tr('Save')}</button></form>` : `<p><b>${esc(r.name || '')}</b></p>`}
      ${ch && man && r.org_id ? `<div class="row"><label class="chkl"><input type="checkbox" id="tcx-open" ${r.open ? 'checked' : ''}> ${tr('Open to the whole organisation')}</label></div>` : ch ? `<p class="muted tcxhint">${r.open ? tr('Open to the whole organisation') : tr('Invited people only')}</p>` : ''}
      <h4>${tr('Members')} <span class="muted">${mem.length}</span></h4><div class="tcxmem">${mem.map(m => `<div class="tcxrow">${av(m.id, m.name, 'avatar sm')}<span class="tcxn">${esc(m.name)}${m.agent ? agentBadge() : ''}</span>${ch && man && m.id !== S.me.id ? `<button type="button" class="iconbtn" data-xs="rm" data-uid="${m.id}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove') + ': ' + m.name)}">${ic('x', 's')}</button>` : ''}</div>`).join('')}</div>
      ${add.length ? `<div class="row"><label for="tcx-add">${tr('Add someone')}</label><select id="tcx-add"><option value="">${tr('Choose')}</option>${add.map(id => `<option value="${id}">${esc(S.tc.users[id] || '?')}</option>`).join('')}</select></div>` : ''}
      <div class="foot">${ids.has(S.me.id) ? `<button type="button" class="btn" data-xs="leave">${ic('logout', 's')}${tr('Leave')}</button>` : ''}${ch && man ? `<button type="button" class="btn" data-xs="archive">${ic('archive', 's')}${tr('Archive')}</button>` : ''}<span class="spacer"></span><button type="button" class="btn pri" data-xs="close">${tr('Done')}</button></div>`;
  };
  const after = async () => { await tcx_refresh(rid); if (md.isConnected) draw(); };
  draw();
  md.addEventListener('submit', async e => {
    e.preventDefault(); const was = room.kind === 'group' ? S.tc.room.custom_name || '' : S.tc.room.name, v = $('#tcx-name', md).value.trim();
    if (v === was || (ch && !v)) return;
    if (!await tcx_req('PATCH', `/api/team/rooms/${rid}`, {name: v})) return;
    step(tr('Renamed to “{0}”', v || tr('the members')), () => patch({name: was}), () => patch({name: v})); after();
  });
  md.addEventListener('change', async e => {
    if (e.target.id === 'tcx-open') { const on = e.target.checked; if (!await tcx_req('PATCH', `/api/team/rooms/${rid}`, {open: on})) { e.target.checked = !on; return; }
      step(on ? tr('Open to the whole organisation') : tr('Invited people only'), () => patch({open: !on}), () => patch({open: on})); after(); }
    else if (e.target.id === 'tcx-add' && e.target.value) { const uid = +e.target.value;
      if (!await tcx_req('POST', `/api/team/rooms/${rid}/members`, {user_id: uid})) { e.target.value = ''; return; }
      step(tr('{0} added', S.tc.users[uid] || '?'), () => rawFetch('DELETE', `/api/team/rooms/${rid}/members/${uid}`), () => rawFetch('POST', `/api/team/rooms/${rid}/members`, {user_id: uid})); after(); }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-xs]'); if (!b) return;
    const a = b.dataset.xs;
    if (a === 'close') { md.remove(); return; }
    if (a === 'rm') { const uid = +b.dataset.uid, nm = (S.tc.room.members.find(m => m.id === uid) || {}).name || '?';
      if (!await tcx_req('DELETE', `/api/team/rooms/${rid}/members/${uid}`)) return;
      step(tr('{0} removed', nm), () => rawFetch('POST', `/api/team/rooms/${rid}/members`, {user_id: uid}), () => rawFetch('DELETE', `/api/team/rooms/${rid}/members/${uid}`)); after(); }
    else if (a === 'archive') { if (!await tcx_req('PATCH', `/api/team/rooms/${rid}`, {archived: true})) return;
      md.remove(); step(tr('Channel archived'), () => patch({archived: false}), () => patch({archived: true})); await tcx_refresh(rid); }
    else if (a === 'leave') {
      const back = ch && room.open && room.org_id;  // an open channel: joining again is the undo
      if (!back && !await askConfirm(tr('Leave this conversation?'), tr('You can only come back when someone adds you again.'), {ok: tr('Leave'), danger: true})) return;
      if (!await tcx_req('DELETE', `/api/team/rooms/${rid}/members/${S.me.id}`)) return;
      md.remove();
      if (back) step(tr('Left the channel'), () => rawFetch('POST', `/api/team/rooms/${rid}/members`, {user_id: S.me.id}), () => rawFetch('DELETE', `/api/team/rooms/${rid}/members/${S.me.id}`));
      else toast(tr('You left the conversation'));
      await loadTeam(); go('team');
    }
  });
}
// a shared list's own chat, from its header / menu
async function listChat(lid) {
  if (!teamOn()) return;
  if (S.tc.rooms === null) await loadTeam();
  const find = () => (S.tc.rooms || []).find(x => x.kind === 'list' && x.list_id === lid);
  // 2.46.1 (#1639): a list shared (with a person or an agent that listens in) since the rooms were loaded: load them again
  let r = find();
  if (!r) { await loadTeam(); r = find(); }
  if (r) go('team/' + r.id); else toast(tr('Share the list with someone to chat about it.'));
}

// ------------------------------------------------------------------ #442 notes of a list / project
// #notes/<list id> = the notes of a list, #note/<id> = one note (its address to share). Markdown with a preview, #123
// links that task, tags, pinned first; saved by itself (a moment after typing, when leaving a field); another person's
// change in between shows both versions.
S.nt = {lid: null, id: null, notes: null, mayWrite: false, q: '', edit: false, saveT: null, dirty: false, err: null};
const notesOf = lid => (S.notes || []).filter(n => n.list_id === lid);
const notesOn = l => !!l && !l.is_inbox && !(l.role === 'participant');
async function loadNotes(lid) {
  try { const j = await rawFetch('GET', `/api/lists/${lid}/notes`); if (S.nt.lid !== lid) return; S.nt.notes = j.notes; S.nt.mayWrite = j.may_write; S.nt.err = null; }
  catch (e) { S.nt.err = e instanceof Offline ? tr('Notes are only available online.') : e.message; }
}
// #123 -> a link to that task (only tasks I see; text inside code / links / buttons and inside tags stays)
// 2.35.0 (#1096): also in chats, comments and the description, there compact (only "#123", the title in the tooltip);
// every tag is skipped whole (no match inside an attribute), "&#39;" is no task number
function mdTaskRefs(html, compact) {
  let skip = 0;
  return html.replace(/<(\/?)([a-zA-Z][\w-]*)[^>]*>|\b[Jj][Oo][Bb] ?#?(\d{1,9})\b|(?<![&\w/#])#(\d{1,9})\b/g, (m, cl, tag, jid, id) => {
    if (tag) { if (/^(code|a|pre|button)$/i.test(tag)) skip = Math.max(0, skip + (cl ? -1 : 1)); return m; }
    if (skip > 0) return m;
    if (jid) return jobRefHtml(+jid, m);  // 2.36.2 (#1141): "Job #50" / "job 50" is a job, not task #50
    const t = taskById(+id); if (!t) return m;  // not visible to me: stays text (no title leaks)
    return trefHtml(t, compact);
  });
}
// 2.36.2 (#1141): a job number links to the job (#job/<id>: Agents > Jobs, that job unfolded with its history), only a job
// I may see: the server is asked once per number (GET /api/agents/jobs?id=); until it answered (or when it is not mine)
// the text stays plain text
const JOBREF = {ok: new Set(), no: new Set(), q: new Set()};
function jobRefHtml(id, txt) {
  if (JOBREF.ok.has(id)) return `<a href="#job/${id}" class="jref" data-jref="${id}">${txt}</a>`;
  if (JOBREF.no.has(id)) return txt;
  jobRefAsk(id);
  return `<span class="jrefq" data-jq="${id}">${txt}</span>`;
}
function jobRefAsk(id) {
  if (JOBREF.q.has(id)) return;
  JOBREF.q.add(id);
  api('GET', '/api/agents/jobs?id=' + id).then(j => { ((j && j.jobs) || []).some(x => x.id === id) ? JOBREF.ok.add(id) : JOBREF.no.add(id); })
    .catch(() => {}).finally(() => {  // offline: asked again with the next drawing
      JOBREF.q.delete(id);
      for (const e of document.querySelectorAll(`.jrefq[data-jq="${id}"]`)) if (JOBREF.ok.has(id) || JOBREF.no.has(id)) e.outerHTML = jobRefHtml(id, e.innerHTML);
    });
}
const trefHtml = (t, compact) => `<a href="#t/${t.id}" class="tref" data-tref="${t.id}" title="${esc(mdPlain(t.title))}">#${t.id}${compact ? '' : ' ' + esc(mdPlain(t.title).slice(0, 60))}</a>`;  // 2.40.0 (#1409): plain
// a tap on a task number opens the task on top of where I am (the chat stays open below it; on a phone Back closes the
// task and shows the chat again); Ctrl / Cmd / middle click open it in a new tab as any link
function trefOpen(e) {
  const a = e.target.closest?.('a[data-tref]');
  if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button || !taskById(+a.dataset.tref)) return;  // not loaded: the link's own route (#t/<id>) finds it
  e.preventDefault(); e.stopPropagation();
  openDetail(+a.dataset.tref);
}
document.addEventListener('click', trefOpen, true);
function noteRoute(lid, id) {
  if (!lid) { noteFlush(); S.nt = {...S.nt, lid: null, id: null, notes: null}; return; }  // 2.45.0 (#1516): the overview of all notes
  if (S.nt.lid !== lid) { S.nt = {...S.nt, lid, notes: null, err: null}; loadNotes(lid).then(() => { if (S.route.mod === 'notes') renderView(); }); }
  if (S.nt.id !== id) { noteFlush(); S.nt.id = id; S.nt.edit = !!id && S.nt.newId === id; S.nt.newId = null; }
}
function viewNotes() {
  if (!S.nt.lid) return sb_notesView();  // 2.45.0 (#1516)
  const l = listById(S.nt.lid);
  if (!l) return botEmpty('ruhig', tr('This list does not exist (any more).'));
  const ns = S.nt.notes;
  if (!ns) return `<div class="muted mhint">${S.nt.err ? esc(S.nt.err) : tr('Loading…')}</div>`;
  const q = S.nt.q.trim().toLowerCase();
  const vis = q ? ns.filter(n => (n.title + ' ' + n.body + ' ' + n.tags.join(' ')).toLowerCase().includes(q)) : ns;
  const cur = S.nt.id && ns.find(n => n.id === S.nt.id);
  const list = `<div class="ntlist ${cur ? 'hasnote' : ''}">
    <div class="ntbar"><div class="ssearch">${ic('search', 's')}<input id="nt-q" type="search" value="${esc(S.nt.q)}" placeholder="${esc(tr('Search notes'))}" aria-label="${esc(tr('Search notes'))}" autocomplete="off"></div>
      ${S.nt.mayWrite ? `<button type="button" class="btn sm pri" data-act="nt-new">${ic('plus', 's')}${tr('New note')}</button>` : ''}</div>
    <div id="nt-res">${ntCardsHtml(vis, q, cur)}</div>
  </div>`;
  return `<div class="ntwrap"><div class="ntview ${cur ? 'open' : ''}">${list}${cur ? `<article class="ntedit" aria-label="${esc(cur.title)}">${noteEditHtml(cur)}</article>` : ''}</div></div>`;
}
// the cards alone: typing in the search field re-renders only these (the field keeps the focus)
function ntCardsHtml(vis, q, cur) {
  return `${vis.length ? `<ul class="ntcards" aria-label="${esc(tr('Notes'))}">${vis.map(n => `<li><a href="#note/${n.id}" class="ntcard ${cur && cur.id === n.id ? 'on' : ''}" ${cur && cur.id === n.id ? 'aria-current="true"' : ''}>
        <span class="ntt">${n.pinned ? `<span class="ntpin" title="${esc(tr('Pinned'))}">${ic('pin', 's')}</span>` : ''}${esc(n.title)}</span>
        <span class="ntx">${esc(n.body.replace(/^#{1,6}\s+/gm, '').replace(/[*_`>\[\]]/g, '').replace(/\s+/g, ' ').trim().slice(0, 140))}</span>
        <span class="ntm">${n.tags.map(t => `<span class="tag">#${esc(t)}</span>`).join('')}<time title="${esc(fmtWhen(n.updated_at))}">${esc(relTime(n.updated_at))}</time>${n.updated_by_name ? `<span class="muted">· ${esc(n.updated_by_name)}</span>` : ''}</span></a></li>`).join('')}</ul>`
      : q ? `<div class="empty">${tr('No notes match.')}</div>` : botEmpty('ruhig', tr('No notes yet.'), S.nt.mayWrite ? tr('Meeting notes, briefings, decisions: write them next to the tasks.') : '')}`;
}
function noteEditHtml(n) {
  const ro = !S.nt.mayWrite, edit = S.nt.edit && !ro;
  return `<div class="nthead">${isMobile() ? `<button type="button" class="iconbtn" data-act="nt-close" aria-label="${esc(tr('Back'))}">${ic('back')}</button>` : ''}
    <input id="nt-title" class="nttitle" value="${esc(n.title)}" aria-label="${esc(tr('Title'))}" maxlength="300" ${ro ? 'readonly' : ''}>
    ${ro ? '' : `<button type="button" class="iconbtn ${n.pinned ? 'on' : ''}" data-act="nt-pin" aria-pressed="${n.pinned}" title="${esc(n.pinned ? tr('Unpin') : tr('Pin'))}" aria-label="${esc(tr('Pin'))}">${ic('pin')}</button>
    <button type="button" class="iconbtn" data-act="nt-menu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button>`}
    ${isMobile() ? '' : `<button type="button" class="iconbtn" data-act="nt-close" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button>`}</div>
    <div class="nttags"><label for="nt-tags">${ic('tag', 's')}<span class="sr">${tr('Tags')}</span></label><input id="nt-tags" value="${esc(n.tags.join(', '))}" placeholder="${esc(tr('Tags, separated by commas'))}" ${ro ? 'readonly' : ''}></div>
    ${ro ? '' : `<div class="seg ntmode" role="group" aria-label="${esc(tr('Mode'))}"><button type="button" data-act="nt-mode" data-m="read" class="${edit ? '' : 'on'}" aria-pressed="${!edit}">${tr('Read')}</button><button type="button" data-act="nt-mode" data-m="edit" class="${edit ? 'on' : ''}" aria-pressed="${edit}">${tr('Edit')}</button></div>`}
    ${edit ? `<textarea id="nt-body" class="ntbody" aria-label="${esc(tr('Text'))}" placeholder="${esc(tr('Markdown: # heading, - list, **bold**, #123 links a task'))}">${esc(n.body)}</textarea>`
      : `<div class="md ntmd" id="nt-md">${n.body.trim() ? mdTaskRefs(renderMd(n.body, false, {lid: S.nt.lid})) : `<p class="muted">${ro ? tr('Empty note.') : tr('Empty note. Switch to Edit to write.')}</p>`}</div>`}
    <div class="ntfoot muted"><span id="nt-saved" role="status" aria-live="polite"></span><span class="spacer"></span><span>${esc(tr('Changed {0}', fmtWhen(n.updated_at)))}${n.updated_by_name ? ' · ' + esc(n.updated_by_name) : ''}</span></div>`;
}
const noteCur = () => S.nt.notes && S.nt.notes.find(n => n.id === S.nt.id);
function noteQueue() { S.nt.dirty = true; clearTimeout(S.nt.saveT); S.nt.saveT = setTimeout(noteFlush, 1200); }
async function noteFlush() {
  clearTimeout(S.nt.saveT);
  const n = noteCur(); if (!n || !S.nt.dirty) return;
  S.nt.dirty = false;
  const t = $('#nt-title'), b = $('#nt-body'), g = $('#nt-tags');
  const patch = {expect_updated_at: n.updated_at};
  if (t && t.value.trim() && t.value.trim() !== n.title) patch.title = t.value.trim();
  if (b && b.value !== n.body) patch.body = b.value;
  if (g) { const tg = g.value.split(',').map(x => x.trim().replace(/^#/, '')).filter(Boolean); if (tg.join() !== n.tags.join()) patch.tags = tg; }
  if (Object.keys(patch).length === 1) return;
  try {
    const r = await rawFetch('PATCH', `/api/notes/${n.id}`, patch);
    Object.assign(n, r); const brief = (S.notes || []).find(x => x.id === n.id); if (brief) Object.assign(brief, {title: r.title, tags: r.tags, pinned: r.pinned, updated_at: r.updated_at});
    const s = $('#nt-saved'); if (s) { s.textContent = tr('Saved'); setTimeout(() => { if (s.isConnected) s.textContent = ''; }, 1500); }
  } catch (e) {
    if (e.status === 409 && e.data?.note) { noteConflict(n, e.data.note, patch); return; }
    S.nt.dirty = true; toast(e instanceof Offline ? tr('You are offline: the note is saved as soon as the server is reachable') : e.message);
  }
}
async function noteConflict(mine, theirs, patch) {
  const keep = await askDialog({title: tr('Changed in the meantime by {0}', theirs.updated_by_name || '?'), html: `<p>${tr('Keep your version or take theirs?')}</p><div class="ntdiff"><div><b>${tr('Yours')}</b><pre>${esc(patch.body ?? mine.body)}</pre></div><div><b>${tr('Theirs')}</b><pre>${esc(theirs.body)}</pre></div></div>`, ok: tr('Keep mine'), cancel: tr('Take theirs')});
  if (keep) {
    try { const r = await rawFetch('PATCH', `/api/notes/${mine.id}`, {...patch, expect_updated_at: theirs.updated_at}); Object.assign(mine, r); } catch (e) { toast(e.message); }
  } else Object.assign(mine, theirs);
  renderView();
}
async function noteNew() {
  const lid = S.nt.lid;
  let r; try { r = await rawFetch('POST', `/api/lists/${lid}/notes`, {title: tr('New note')}); } catch (e) { toast(e.message); return; }
  S.nt.notes = [r, ...(S.nt.notes || [])]; S.notes = [{id: r.id, list_id: lid, title: r.title, tags: [], pinned: false, updated_at: r.updated_at}, ...(S.notes || [])];
  S.nt.newId = r.id; go('note/' + r.id);
  setTimeout(() => { const t = $('#nt-title'); if (t) { t.focus(); t.select(); } }, 120);
}
function noteMenu(anchor) {
  const n = noteCur(); if (!n) return;
  const others = S.lists.filter(l => !l.archived && l.id !== n.list_id && canEditList(l.id) && notesOn(l));
  menu(anchor, [{label: tr('Copy link'), icon: 'link', fn: () => { navigator.clipboard?.writeText(`${location.origin}${location.pathname}#note/${n.id}`).then(() => toast(tr('Link copied'))); }},
    ...(others.length ? [{label: tr('Move to list…'), icon: 'folder', fn: () => tch_listPicker(anchor, {filter: l => others.includes(l), pick: async l => {  // 2.38.0 (#1177)
      try { const r = await rawFetch('PATCH', `/api/notes/${n.id}`, {list_id: l.id}); Object.assign(n, r); } catch (e) { toast(e.message); return; }
      await load(); toast(tr('Moved to {0}', lname(l))); go('note/' + n.id); }})}] : []),
    '-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: async () => {
      let r; try { r = await rawFetch('DELETE', `/api/notes/${n.id}`); } catch (e) { toast(e.message); return; }
      S.nt.notes = S.nt.notes.filter(x => x.id !== n.id); S.notes = (S.notes || []).filter(x => x.id !== n.id);
      go('notes/' + n.list_id); setTimeout(() => { if (document) $('#nt-q')?.focus(); }, 80);  // 2.17.2: the focus stays in the notes
      toast(tr('Note deleted'), async () => {  // undo: the same note again (a new id)
        try { const x = await rawFetch('POST', `/api/lists/${r.note.list_id}/notes`, {title: r.note.title, body: r.note.body, tags: r.note.tags, pinned: r.note.pinned}); S.nt.notes = [x, ...S.nt.notes]; await load(); go('note/' + x.id); setTimeout(() => { if (document) $('#nt-title')?.focus(); }, 120); } catch (e) { toast(e.message); }
      });
    }}]);
}
document.addEventListener('input', e => {
  if (e.target.id === 'nt-q') {
    S.nt.q = e.target.value; const r = $('#nt-res'), ns = S.nt.notes || [], q = S.nt.q.trim().toLowerCase();
    if (!r) return;
    const vis = q ? ns.filter(n => (n.title + ' ' + n.body + ' ' + n.tags.join(' ')).toLowerCase().includes(q)) : ns;
    fl_set(r, ntCardsHtml(vis, q, S.nt.id && ns.find(n => n.id === S.nt.id)));
    clearTimeout(S.nt.qT); S.nt.qT = setTimeout(() => { if (document && q) announce(trn('{0} note', '{0} notes', vis.length)); }, 600);
    return;
  }
  if (['nt-title', 'nt-body', 'nt-tags'].includes(e.target.id)) { if (e.target.id === 'nt-body') autosize(e.target); noteQueue(); }
});
document.addEventListener('focusout', e => { if (['nt-title', 'nt-body', 'nt-tags'].includes(e.target.id)) noteFlush(); });
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="nt-"]'); if (!a) return;
  const act = a.dataset.act, n = noteCur();
  if (act === 'nt-new') noteNew();
  else if (act === 'nt-close') { noteFlush(); go('notes/' + S.nt.lid); }
  else if (act === 'nt-mode') { noteFlush(); S.nt.edit = a.dataset.m === 'edit'; renderView(); if (S.nt.edit) setTimeout(() => { const b = $('#nt-body'); if (b) { autosize(b); b.focus(); } }, 0); }
  else if (act === 'nt-pin' && n) { rawFetch('PATCH', `/api/notes/${n.id}`, {pinned: !n.pinned}).then(r => { Object.assign(n, r); renderView(); }).catch(err => toast(err.message)); }
  else if (act === 'nt-menu') noteMenu(a);
  else return;
  e.preventDefault(); e.stopPropagation();
});

// ------------------------------------------------------------------ 2.33.0 (#1080) search in conversations
// Task comments, team chat (channels, direct messages) and agent chats. msgSearch(q, filters) merges the hits of every source
// (newest first). Today there is one source, the server (kalmido/collab/msgsearch.py: only what the person may read). 2.34
// (#909) adds a device source for end-to-end encrypted direct messages, which the server cannot read:
// MSG_SOURCES.push({id: 'device', search: async (q, f) => ({hits, total, next})}) -- a hit is {art: c|t|a, id, chat_type:
// task|list|dm|agent, task_id?, room_id?, agent_id?, chat_name, sender: {id, name, agent}, created_at, snippet, marks}.
// Three places use it: the search field of an open chat (the magnifier in its header), the "Messages" part of the command
// field (palette.js) and of the search page (render.js viewSearch) with filter chips. A hit opens through msgJump (collab.js).
const MSG_SOURCES = [{id: 'server', search: async (q, f = {}) => {
  const p = new URLSearchParams({q});
  for (const k of ['art', 'sender', 'room', 'agent', 'task', 'limit', 'offset']) if (f[k] != null && f[k] !== '') p.set(k, f[k]);
  const j = await rawFetch('GET', '/api/search/messages?' + p);
  return {hits: j.hits || [], total: j.total || 0, next: j.next_offset ?? null};
}}];
async function msgSearch(q, f = {}) {
  const rs = await Promise.allSettled(MSG_SOURCES.map(s => s.search(q, f)));
  const ok = rs.filter(r => r.status === 'fulfilled').map(r => r.value);
  if (!ok.length && rs.length) throw rs[0].reason;
  const seen = new Set(), hits = [];
  for (const r of ok) for (const h of r.hits) { const k = h.art + ':' + h.id; if (!seen.has(k)) { seen.add(k); hits.push(h); } }
  hits.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '') || b.id - a.id);
  return {hits, total: ok.reduce((n, r) => n + (r.total || 0), 0), next: ok.find(r => r.next != null)?.next ?? null};
}
const MSG_KIND = {task: N_('Comment'), list: N_('Team chat'), dm: N_('Direct message'), agent: N_('Agent chat'), channel: N_('Channel'), group: N_('Group')};  // 2.113.1 (#2059): + channel, group
const msgIcon = h => h.chat_type === 'agent' ? 'bot' : h.chat_type === 'list' || h.chat_type === 'group' ? 'users' : h.chat_type === 'channel' ? 'hash' : h.chat_type === 'dm' ? 'user' : 'comment';
// the snippet with its hits as <mark> (marks count code points, like the server)
function msgSnip(h) {
  const cs = Array.from(h.snippet || ''); let o = '', at = 0;
  for (const [s, e] of h.marks || []) { if (s < at) continue; o += esc(cs.slice(at, s).join('')) + '<mark>' + esc(cs.slice(s, e).join('')) + '</mark>'; at = e; }
  return o + esc(cs.slice(at).join(''));
}
function msgOpen(h) {
  if (!h) return;
  return window.msgJump?.({art: h.art, id: h.id, task: h.task_id, chat: h.room_id, agent: h.agent_id});
}
function msgHitHtml(h, i, act) {
  return `<button type="button" class="mhit" data-act="${act}" data-i="${i}"><span class="mhic">${ic(msgIcon(h), 's')}</span><span class="mhm">
    <span class="mhh"><b>${esc(h.sender?.name || '?')}</b><span class="mhc">${esc(tr(MSG_KIND[h.chat_type] || ''))}${h.chat_name ? ' · ' + esc(h.chat_name) : ''}</span><time datetime="${esc(h.created_at || '')}">${h.created_at ? esc(fmtWhen(h.created_at)) : ''}</time></span>
    <span class="mhs">${msgSnip(h)}</span></span></button>`;
}
// the words of a query, folded like the server (case, accents; ä = ae): marking them in a message on the screen
const msgWords = q => (String(q || '').match(/[\p{L}\p{N}_]+/gu) || []).slice(0, 8);
const msgFoldCh = ch => ch === 'ß' ? 'ss' : ch.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
function msgVariants(w) {
  const f = Array.from(w).map(msgFoldCh).join(''), x = Array.from(w.replace(/[äöüÄÖÜ]/g, c => c + 'e')).map(msgFoldCh).join('');
  return [...new Set([f, x, f.replace(/ae/g, 'a').replace(/oe/g, 'o').replace(/ue/g, 'u')])];
}
function msgUnmark() { $$('mark.mshl').forEach(m => { const p = m.parentNode; if (!p) return; p.replaceChild(document.createTextNode(m.textContent), m); p.normalize(); }); }
function msgMark(el, q) {
  msgUnmark(); if (!el) return;
  const vs = msgWords(q).flatMap(msgVariants).filter(Boolean); if (!vs.length) return;
  const root = $('.cbub, .cbody, .cmbody', el) || el, nodes = [], tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (tw.nextNode()) nodes.push(tw.currentNode);
  for (const n of nodes) {
    const t = n.nodeValue, chars = Array.from(t); let f = '', pos = [], off = 0;
    for (const ch of chars) { const x = msgFoldCh(ch); f += x; for (let k = 0; k < x.length; k++) pos.push(off); off += ch.length; }
    const rng = [];
    for (const v of vs) { let i = -1; while ((i = f.indexOf(v, i + 1)) >= 0) { if (i > 0 && /[\p{L}\p{N}_]/u.test(f[i - 1])) continue; const s = pos[i], e = i + v.length < pos.length ? pos[i + v.length] : t.length; rng.push([s, Math.max(e, s + 1)]); } }
    if (!rng.length) continue;
    rng.sort((a, b) => a[0] - b[0]);
    const frag = document.createDocumentFragment(); let at = 0;
    for (const [s, e] of rng) { if (s < at) continue; frag.append(t.slice(at, s)); const m = document.createElement('mark'); m.className = 'mshl'; m.textContent = t.slice(s, e); frag.append(m); at = e; }
    frag.append(t.slice(at)); n.parentNode.replaceChild(frag, n);
  }
}

// ---- the search field of an open chat: art t (a team chat room) or a (the chat with an agent); key = room / agent id
S.ms = {open: false, art: null, key: null, q: '', hits: [], i: -1, busy: false, t: 0};
const msOpenFor = (art, key) => S.ms.open && S.ms.art === art && S.ms.key === key;
const msgSearchBtn = (art, key) => `<button type="button" class="iconbtn msbtn ${msOpenFor(art, key) ? 'on' : ''}" data-act="ms-toggle" data-art="${art}" data-key="${key}" aria-expanded="${msOpenFor(art, key)}" title="${esc(tr('Search in this chat'))}" aria-label="${esc(tr('Search in this chat'))}">${ic('search')}</button>`;
function msCount() {
  const m = S.ms;
  return m.busy ? tr('Searching…') : !m.q.trim() ? '' : !m.hits.length ? tr('No hits') : tr('{0} of {1}', m.i + 1, m.hits.length);
}
function msBarHtml(art, key) {
  if (!msOpenFor(art, key)) return '';
  const n = S.ms.hits.length;
  return `<div class="mqbar" role="search"><span class="msico" aria-hidden="true">${ic('search', 's')}</span><input id="ms-q" type="search" value="${esc(S.ms.q)}" placeholder="${esc(tr('Search in this chat'))}" aria-label="${esc(tr('Search in this chat'))}" autocomplete="off" enterkeyhint="search">
    <span class="mscount" aria-live="polite">${esc(msCount())}</span>
    <button type="button" class="iconbtn" data-act="ms-older" ${n && S.ms.i < n - 1 ? '' : 'disabled'} title="${esc(tr('Older hit'))}" aria-label="${esc(tr('Older hit'))}">${ic('up', 's')}</button>
    <button type="button" class="iconbtn" data-act="ms-newer" ${n && S.ms.i > 0 ? '' : 'disabled'} title="${esc(tr('Newer hit'))}" aria-label="${esc(tr('Newer hit'))}">${ic('down', 's')}</button>
    <button type="button" class="iconbtn" data-act="ms-close" title="${esc(tr('Close search'))}" aria-label="${esc(tr('Close search'))}">${ic('x', 's')}</button></div>`;
}
// the bar sits right under the chat's header (drawn with it, and swapped in place when the chat is not drawn again)
function msBarSync(focus) {
  const bar = $('.mqbar'), btn = S.ms.art ? $(`[data-act="ms-toggle"][data-art="${S.ms.art}"][data-key="${S.ms.key}"]`) : null;
  $$('[data-act="ms-toggle"]').forEach(b => { const on = msOpenFor(b.dataset.art, +b.dataset.key); b.classList.toggle('on', on); b.setAttribute('aria-expanded', on); });
  if (!S.ms.open || !btn) { bar?.remove(); return; }
  const head = btn.closest('.tcrhead, .chath'); if (!head) return;
  if (bar && bar.previousElementSibling === head) {  // keep the field (its caret, the keyboard): only the counter + arrows
    const tmp = document.createElement('div'); tmp.innerHTML = msBarHtml(S.ms.art, S.ms.key);
    $('.mscount', bar).textContent = msCount();
    for (const a of ['ms-older', 'ms-newer']) $(`[data-act="${a}"]`, bar).disabled = $(`[data-act="${a}"]`, tmp).disabled;
  } else { bar?.remove(); head.insertAdjacentHTML('afterend', msBarHtml(S.ms.art, S.ms.key)); }
  if (focus) { $('#ms-q')?.focus(); msKbSync(); }  // 2.34.0 (#1091): also where the focus event does not come (a window without focus)
}
function msSearchToggle(art, key) {
  if (msOpenFor(art, key)) { msClose(); return; }
  Object.assign(S.ms, {open: true, art, key, q: '', hits: [], i: -1, busy: false});
  msBarSync(true);
}
function msClose() {
  const f = document.activeElement?.id === 'ms-q';
  Object.assign(S.ms, {open: false, q: '', hits: [], i: -1}); msgUnmark(); msBarSync();
  if (f) (S.ms.art === 't' ? $('#tc-in') : $('#chat-in'))?.focus({preventScroll: true});
  setTimeout(msKbSync, 0);  // 2.34.0 (#1091)
}
async function msRun(q) {
  const m = S.ms, art = m.art, key = m.key; m.q = q;
  if (!q.trim()) { Object.assign(m, {hits: [], i: -1, busy: false}); msgUnmark(); msBarSync(); return; }
  m.busy = true; msBarSync();
  let r;
  try { r = await msgSearch(q, {art, [art === 't' ? 'room' : 'agent']: key, limit: 50}); }
  catch (e) { if (m.q === q) { m.busy = false; msBarSync(); toast(e instanceof Offline ? tr('Only available online.') : e.message); } return; }
  if (m.q !== q || m.art !== art || m.key !== key || !m.open) return;
  Object.assign(m, {hits: r.hits, i: r.hits.length ? 0 : -1, busy: false}); msBarSync();
  if (r.hits.length) msGo(0);
  else msgUnmark();
}
async function msGo(i) {
  const m = S.ms, h = m.hits[i]; if (!h) return;
  m.i = i; msBarSync();
  const q = m.q, ok = await msgOpen(h);
  if (ok && m.open && m.q === q) msgMark($(`[data-mid="${h.art}:${h.id}"]`), q);
}
// 2.34.0 (#1091): on a touch screen the keyboard comes up with the chat's search field: the tab bar (and the "+") step aside
// like for the message box (body.ms-typing; the agent chat then fits its height again)
function msKbSync() {
  const on = document.activeElement?.id === 'ms-q' && coarseOnly();
  if (document.body.classList.contains('ms-typing') === on) return;
  document.body.classList.toggle('ms-typing', on);
  if (typeof chatFit === 'function') chatFit();
}
document.addEventListener('focusin', e => { if (e.target.id === 'ms-q' || document.body.classList.contains('ms-typing')) msKbSync(); });
document.addEventListener('focusout', e => { if (e.target.id === 'ms-q') setTimeout(msKbSync, 0); });
document.addEventListener('input', e => {
  if (e.target.id !== 'ms-q') return;
  const q = e.target.value; S.ms.q = q; clearTimeout(S.ms.t); S.ms.t = setTimeout(() => msRun(q), 300);
});
document.addEventListener('keydown', e => {
  if (e.target.id !== 'ms-q') return;
  if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); if (S.ms.q !== e.target.value || !S.ms.hits.length) { clearTimeout(S.ms.t); msRun(e.target.value); } else msGo(e.shiftKey ? Math.max(0, S.ms.i - 1) : Math.min(S.ms.hits.length - 1, S.ms.i + 1)); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); msGo(Math.min(S.ms.hits.length - 1, S.ms.i + 1)); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); msGo(Math.max(0, S.ms.i - 1)); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); msClose(); }
}, true);
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="ms-"]'); if (!a) return;
  const act = a.dataset.act;
  if (act === 'ms-toggle') msSearchToggle(a.dataset.art, +a.dataset.key);
  else if (act === 'ms-older') msGo(Math.min(S.ms.hits.length - 1, S.ms.i + 1));
  else if (act === 'ms-newer') msGo(Math.max(0, S.ms.i - 1));
  else if (act === 'ms-close') msClose();
  else if (act === 'ms-hit') msgOpen(S.msg.hits[+a.dataset.i]);
  else if (act === 'ms-art') { S.msg.art = a.dataset.v; msgSecRun(S.msg.q); }
  else if (act === 'ms-more') msgSecRun(S.msg.q, true);
  else return;
  e.preventDefault(); e.stopPropagation();
});
document.addEventListener('change', e => { if (e.target.id === 'ms-sender') { S.msg.sender = e.target.value; msgSecRun(S.msg.q); } });

// ---- "Messages" on the search page: filter chips (all / comments / team chats / agent chats), the sender, more pages
S.msg = {q: '', art: '', sender: '', hits: [], total: 0, next: null, busy: false, err: null, senders: {}};
const MSG_CHIPS = [['', N_('All')], ['c', N_('Comments')], ['t', N_('Team chats')], ['a', N_('Agent chats')]];
function msgSecHtml() {
  const m = S.msg; if (!m.q.trim()) return '';
  const snd = Object.entries(m.senders).sort((a, b) => a[1].localeCompare(b[1], LOCALE()));
  return `<section class="msec" aria-labelledby="msec-h"><h2 class="ghead" id="msec-h">${tr('Messages')} ${m.busy ? '' : `<span class="c">${m.total}</span>`}</h2>
    <div class="mschips" role="group" aria-label="${esc(tr('Show'))}">${MSG_CHIPS.map(([v, n]) => `<button type="button" class="chip ${m.art === v ? 'on' : ''}" data-act="ms-art" data-v="${v}" aria-pressed="${m.art === v}">${esc(tr(n))}</button>`).join('')}
    ${snd.length > 1 || m.sender ? `<select id="ms-sender" aria-label="${esc(tr('Sender'))}"><option value="">${esc(tr('All senders'))}</option>${snd.map(([id, n]) => `<option value="${id}" ${String(m.sender) === id ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>` : ''}</div>
    <div class="mslist">${m.err ? `<div class="muted mhint">${esc(m.err)}</div>` : m.hits.length ? m.hits.map((h, i) => msgHitHtml(h, i, 'ms-hit')).join('') : m.busy ? `<div class="muted mhint">${tr('Searching…')}</div>` : `<div class="muted mhint">${tr('No messages found.')}</div>`}</div>
    ${m.next != null ? `<button type="button" class="btn sm msmore" data-act="ms-more">${tr('Show more')}</button>` : ''}</section>`;
}
function msgSecDraw() { const el = $('#smsgs'); if (el) fl_set(el, msgSecHtml()); }  // 2.46.2 (#1718): morphed
async function msgSecRun(q, more = false) {
  const m = S.msg;
  if (q !== m.q) { m.senders = {}; m.sender = ''; }
  m.q = q; m.err = null;
  if (!q.trim()) { Object.assign(m, {hits: [], total: 0, next: null}); msgSecDraw(); return; }
  m.busy = true; if (!more) { m.hits = []; m.next = null; } msgSecDraw();
  const f = {art: m.art, sender: m.sender, limit: 20, offset: more ? m.next || 0 : 0};
  let r;
  try { r = await msgSearch(q, f); }
  catch (e) { if (m.q === q) { m.busy = false; m.err = e instanceof Offline ? tr('Only available online.') : e.message; msgSecDraw(); } return; }
  if (m.q !== q || m.art !== f.art || m.sender !== f.sender) return;
  m.busy = false; m.hits = more ? [...m.hits, ...r.hits] : r.hits; m.total = r.total; m.next = r.next;
  for (const h of r.hits) if (h.sender?.id) m.senders[h.sender.id] = h.sender.name;
  msgSecDraw();
}

// ---- the command field (palette.js): up to 5 hits as the group "Messages", "All messages" opens the search page
const PALM = {q: '', hits: null, total: 0, t: 0};
function palMsgItems(q) {
  q = q.trim();
  if (q.length < 2 || !collab() && !feat('agents') && !feat('comments')) return [];
  if (PALM.q !== q) {
    PALM.q = q; PALM.hits = null; clearTimeout(PALM.t);
    PALM.t = setTimeout(async () => {
      let r; try { r = await msgSearch(q, {limit: 5}); } catch { return; }
      if (PALM.q !== q) return;
      PALM.hits = r.hits; PALM.total = r.total;
      if ($('.palette') && PAL.q.trim() === q) palDraw();
    }, 250);
    return [];
  }
  if (!PALM.hits?.length) return [];
  const it = PALM.hits.map((h, i) => ({id: 'msg:' + h.art + h.id + ':' + i, kind: 'msg', group: 'msgs', label: `${h.sender?.name || '?'} · ${h.chat_name || tr(MSG_KIND[h.chat_type])}`, subHtml: msgSnip(h), icon: msgIcon(h), fn: () => msgOpen(h)}));
  if (PALM.total > PALM.hits.length) it.push({id: 'msg:all', kind: 'msg', group: 'msgs', label: tr('All {0} messages', PALM.total), icon: 'search', fn: () => { go('search'); setTimeout(() => { const i = $('#searchq'); if (i) i.value = q; doSearch(q); }, 0); }});
  return it;
}

// ------------------------------------------------------------------ 2.37.0 (#1159): save a chat message as a task
// "Save as task" in the menu of every message (agent chat and team chat, not on deleted ones) and under an agent's message
// that offers it (offer_save; the agent never saves itself). The dialog: title (the first heading or line), the list
// (lists the person may change, the inbox first), "To review by" (optional). The server (POST /api/chat-save) writes the
// whole text, the files and a link back to the message; a message saved before answers "already saved" with its task.
// A saved message shows a small "Saved" mark that opens the task.
function chatSaveTitle(text) {
  const ls = String(text || '').split('\n').map(x => x.trim()).filter(Boolean);
  let t = ls.find(x => /^#{1,6}\s+\S/.test(x)) || ls[0] || '';
  t = t.replace(/^(#{1,6}|>|[-*+]|\d+[.)])\s+/, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, S.tc?.users || {})).replace(/[*_`~]+/g, '').trim();
  return t.length > 120 ? t.slice(0, 119).trimEnd() + '…' : t;
}
async function chatSaveOpen(tid) {
  if (!taskById(tid)) { try { (S.extra ||= []).push(await rawFetch('GET', `/api/tasks/${tid}`)); } catch { toast(tr('Task not found')); return; } }
  openDetail(tid);
}
const chatSavedMark = m => m.saved_task_id ? `<button type="button" class="csaved" data-act="csave-open" data-tid="${m.saved_task_id}" title="${esc(tr('Saved as a task: open it'))}">${ic('bookmark', 's')}<span>${tr('Saved')}</span></button>` : '';
function chatSaveModal(kind, m, done) {
  if (!m || m.deleted) return;
  if (m.saved_task_id) { toast(tr('Already saved as a task'), () => chatSaveOpen(m.saved_task_id), 6000, tr('Open')); return; }
  const ib = inbox(), ls = [ib, ...sideOrder().filter(l => l && !l.is_inbox && !l.archived && canEditList(l.id))].filter(Boolean);
  const cmt = kind === 'comment';  // 2.42.0 (#1383): an agent's comment: a subtask of its task or a new task in the same list
  const md = modal(`<h3>${ic('bookmark', 's')} ${tr('Save as task')}</h3>
    <p class="muted">${cmt ? tr('The task gets the whole comment, its files and a link back to it.') : tr('The task gets the whole message, its files and a link back to it in the chat.')}</p>
    <div class="row"><label for="cs-title">${tr('Title')}</label><input id="cs-title" maxlength="2000" value="${esc(chatSaveTitle(m.body) || tr('Saved message'))}"></div>
    ${cmt ? `<div class="row csas" role="radiogroup" aria-label="${esc(tr('Save as task'))}"><label><input type="radio" name="cs-as" value="sub" checked> ${tr('As a subtask of this task')}</label><label><input type="radio" name="cs-as" value="list"> ${tr('As a new task in the same list')}</label></div>`
    : `<div class="row"><label for="cs-list">${tr('List')}</label><select id="cs-list">${ls.map(l => `<option value="${l.id}" ${l === ib ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>`}
    <div class="row"><label>${tr('To review by')}</label>${dateIn('cs-due', '', {label: tr('To review by'), empty: tr('No date')})}</div>
    <div class="foot"><div class="calerr" role="alert" id="cs-err" hidden></div><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${ic('bookmark', 's')} ${tr('Save')}</button></div>`);
  md.classList.add('csmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const er = $('#cs-err', md); er.hidden = true; b.disabled = true;
    const due = $('#cs-due', md).value, title = $('#cs-title', md).value.trim();
    let j;
    const where = cmt ? {as: $('[name="cs-as"]:checked', md)?.value || 'sub'} : {list_id: +$('#cs-list', md).value};
    try { j = await rawFetch('POST', '/api/chat-save', {kind, msg_id: m.id, ...where, ...(due ? {due} : {}), ...(title ? {title} : {})}); }
    catch (x) { er.textContent = x.message; er.hidden = false; b.disabled = false; return; }
    md.remove();
    const tid = j.already ? j.task_id : j.task?.id;
    m.saved_task_id = tid;
    if (j.task && !j.already) { if (cmt) putTask(j.task); else (S.extra ||= []).push(j.task); }  // 2.42.0 (#1383): a comment's task is in a list I see
    if (done) done();
    toast(j.already ? tr('Already saved as a task') : j.skipped_files?.length ? tr('Saved as a task (without {0}: storage full)', j.skipped_files.join(', ')) : tr('Saved as a task'), () => chatSaveOpen(tid), 6000, tr('Open'));
  });
  setTimeout(() => $('#cs-title', md)?.focus(), 30);
  return md;
}
// 2.46.2 (#1666): every comment (also another person's, also in a read-only list) can be copied like a chat message
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="cm-copy"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const m = (S.tl?.comments || []).find(x => x.id === +a.dataset.cid); if (!m) return;
  menu(a, [{label: tr('Copy'), icon: 'copy', fn: () => chatCopy(S.tl.comments, m, 'comment')},
    {label: tr('Copy as Markdown'), icon: 'copy', fn: () => chatCopy(S.tl.comments, m, 'comment', true)}]);
});
// 2.42.0 (#1383): "Save as task" under an agent's comment in a task (collab.js commentHtml) and its "Saved" mark
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="cm-save"],[data-act="cm-saved"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  if (a.dataset.act === 'cm-saved') { chatSaveOpen(+a.dataset.tid); return; }
  const m = (S.tl?.comments || []).find(x => x.id === +a.dataset.cid); if (!m) return;
  chatSaveModal('comment', m, () => { if (S.sel && S.tl.id === S.sel) loadTimeline(S.sel); });
});
// 2.37.0 (#1165): "Copy" in the menu of a chat message: its Markdown text (mentions as @Name). An answer the sender split
// into parts (each ends with "_(Part 2/3)_", any word) is copied as one text when all its parts are loaded.
// 2.41.0 (#1374): also "_(2/3)_" (the reference launcher's mark); an agent's closing blocks / host notes stay out (rcpClean)
const CPART = /\s*_\((?:\S+ )?(\d+)\/(\d+)\)_\s*$/;
function chatCopyText(msgs, m, kind) {
  const plain = x => { const t = String(x.body || '').replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, (kind === 'comment' ? S.tl?.users : S.tc?.users) || {})); return kind === 'agent' && x.from === 'agent' ? rcpClean(t) : t; };
  const p = plain(m).match(CPART), i = msgs.indexOf(m);
  if (!p || i < 0) return {text: plain(m), n: 1};
  const k = +p[1], n = +p[2], run = msgs.slice(i - k + 1, i - k + 1 + n);
  const whole = k >= 1 && k <= n && i - k + 1 >= 0 && run.length === n && run.every((x, j) => {
    const q = plain(x).match(CPART);
    return q && +q[1] === j + 1 && +q[2] === n && !x.deleted && (kind === 'agent' ? x.from === m.from : x.user_id === m.user_id);
  });
  return whole ? {text: run.map(x => plain(x).replace(CPART, '')).join('\n\n'), n} : {text: plain(m), n: 1};
}
// the clipboard; without navigator.clipboard (an http address, an old browser) a hidden field and execCommand
async function clipCopy(text) {
  try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; } } catch { /* blocked: the old way */ }
  const back = document.activeElement, ta = document.createElement('textarea');
  ta.className = 'cliptmp'; ta.value = text; ta.setAttribute('readonly', ''); ta.setAttribute('aria-hidden', 'true');
  document.body.appendChild(ta); ta.focus({preventScroll: true}); ta.select(); ta.setSelectionRange?.(0, text.length);
  let ok = false; try { ok = !!document.execCommand?.('copy'); } catch { ok = false; }
  ta.remove(); back?.focus?.({preventScroll: true});
  return ok;
}
async function chatCopy(msgs, m, kind, md) {  // 2.41.0 (#1374): with formatting (rcpCopy); md = "Copy as Markdown" (the raw text)
  const {text, n} = chatCopyText(msgs, m, kind);
  toast(await (md ? clipCopy(text) : rcpCopy(text)) ? (n > 1 ? tr('Copied ({0} parts)', n) : tr('Copied')) : tr('Copy failed, select the text by hand'));
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="csave-open"],[data-act="chat-save"],[data-act="chat-msg-menu"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  if (a.dataset.act === 'csave-open') { chatSaveOpen(+a.dataset.tid); return; }
  const m = (S.chat?.msgs || []).find(x => x.id === +a.dataset.mid); if (!m) return;
  if (a.dataset.act === 'chat-save') { chatSaveModal('agent', m, () => chatPatch()); return; }
  const ag = agentById(S.chat.aid);
  menu(a, [ag?.enabled ? {label: tr('Reply'), icon: 'reply', fn: () => replyStart('a', m.id)} : null, m.kind === 'notice' ? null : cpnItem('a', m),  // 2.62.0 (#1848)
    {label: tr('Copy'), icon: 'copy', fn: () => chatCopy(S.chat.msgs, m, 'agent')},  // 2.37.0 (#1165)
    {label: tr('Copy as Markdown'), icon: 'copy', fn: () => chatCopy(S.chat.msgs, m, 'agent', true)},  // 2.41.0 (#1374)
    {label: m.saved_task_id ? tr('Saved as a task: open it') : tr('Save as task'), icon: 'bookmark', fn: () => m.saved_task_id ? chatSaveOpen(m.saved_task_id) : chatSaveModal('agent', m, () => chatPatch())},
    m.from !== 'agent' && ag?.enabled ? {label: tr('Edit'), icon: 'edit', fn: () => chatEditStart(m.id)} : null]);  // 2.39.0 (#1179): my own messages
});
