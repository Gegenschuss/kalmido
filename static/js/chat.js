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
  S.tc.msgs = before ? [...j.messages, ...S.tc.msgs] : j.messages;
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
const roomIcon = r => r.kind === 'dm' ? av(r.user_id, r.name, 'avatar') : `<span class="tcico">${licon(listById(r.list_id), 'licon') || ic('users', 's')}</span>`;
function viewTeam() {
  if (!teamOn()) return `<div class="empty">${tr('The team chat needs collaboration (Settings > Modules).')}</div>`;
  if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.route.mod === 'team') renderView(); }); }
  // 2.27.0 (#986): only conversations that have messages (newest first); an empty one shows once it is opened / written in
  const rid = S.tc.rid, rooms = (S.tc.rooms || []).filter(r => (r.last || r.id === rid) && (r.kind === 'dm' || r.id === rid || inWs(listById(r.list_id))));  // 2.28.0 (#935)
  const list = `<nav class="tclist" aria-label="${esc(tr('Conversations'))}">
    <div class="tchead"><b>${tr('Conversations')}</b><span class="spacer"></span><button type="button" class="btn sm pri" data-act="tc-new" aria-haspopup="${S.tc.people.length ? 'menu' : 'dialog'}">${ic('plus', 's')}${tr('New message')}</button></div>
    ${S.tc.rooms === null ? `<div class="muted mhint">${tr('Loading…')}</div>` : rooms.length ? rooms.map(r => `<button type="button" class="tcrow ${r.id === rid ? 'on' : ''} ${r.unread ? 'unread' : ''}" data-act="tc-open" data-rid="${r.id}" ${r.id === rid ? 'aria-current="true"' : ''}>
      ${roomIcon(r)}<span class="tcmain"><span class="tcn">${esc(roomName(r))}${r.kind === 'list' ? `<span class="tck">${ic('users', 's')}${r.members}</span>` : ''}</span>
      <span class="tclast">${r.last ? esc((r.last.user_id === S.me?.id ? tr('You') + ': ' : r.kind === 'list' ? uname(r.last.user_id, S.tc.users) + ': ' : '') + mdBrief(r.last.text)) : `<span class="muted">${tr('No messages yet')}</span>`}</span></span>
      <span class="tcside">${r.last_at ? `<time>${esc(relTime(r.last_at))}</time>` : ''}${r.unread ? `<span class="nbadge ${r.mention ? 'ment' : ''}" aria-label="${esc(trn('{0} unread', '{0} unread', r.unread))}">${r.mention ? '@' : ''}${r.unread}</span>` : ''}${r.muted ? `<span class="tcmute" title="${esc(tr('Muted'))}">${ic('belloff', 's')}</span>` : ''}</span></button>`).join('')
    : `<div class="empty tcempty">${heron('empty')}<b>${tr('No conversations yet')}</b><span>${S.tc.people.length || (S.tc.rooms || []).length ? tr('Write to someone you work with, or share a list: every shared list gets its own chat.') : tr('Share a list with someone: every shared list gets its own chat.')}</span>${S.tc.people.length || (S.tc.rooms || []).length ? `<button type="button" class="btn sm pri" data-act="tc-new">${ic('plus', 's')}${tr('Start a conversation')}</button>` : ''}</div>`}
  </nav>`;
  return `<div class="tcwrap"><div class="tcview ${rid ? 'inroom' : ''}">${list}${rid ? `<section class="tcroom" aria-label="${esc(roomName(S.tc.room ? {...S.tc.room, name: (rooms.find(x => x.id === rid) || {}).name} : rooms.find(x => x.id === rid)))}">${tcRoomHtml()}</section>` : (isMobile() ? '' : `<section class="tcroom tcnone"><div class="empty">${ic('comment')}<span>${tr('Pick a conversation.')}</span></div></section>`)}</div></div>`;
}
function tcRoomHtml() {
  const rid = S.tc.rid, r = (S.tc.rooms || []).find(x => x.id === rid), room = S.tc.room;
  const name = roomName(r || room);
  const head = `<div class="tcrhead"><button type="button" class="iconbtn tcback" data-act="tc-back" aria-label="${esc(tr('Back'))}">${ic('back')}</button>
    ${r ? roomIcon(r) : ''}<div class="tcrt"><b>${esc(name)}</b>${room && room.kind === 'list' ? `<span class="muted">${esc(room.members.map(m => m.name).slice(0, 6).join(', '))}${room.members.length > 6 ? ' +' + (room.members.length - 6) : ''}</span>` : ''}</div>
    <span class="spacer"></span>${msgSearchBtn('t', rid)}${room && room.kind === 'list' ? `<button type="button" class="iconbtn" data-act="tc-list" data-id="${room.list_id}" title="${esc(tr('Open the list'))}" aria-label="${esc(tr('Open the list'))}">${ic('list')}</button>` : ''}
    <button type="button" class="iconbtn ${room?.muted ? 'on' : ''}" data-act="tc-mute" aria-pressed="${!!room?.muted}" title="${esc(room?.muted ? tr('Muted: only mentions notify you') : tr('Mute (only mentions notify you)'))}" aria-label="${esc(tr('Mute'))}">${ic(room?.muted ? 'belloff' : 'bell')}</button></div>`;
  return `${head}${msBarHtml('t', rid)}<div class="chmsgs tcmsgs" id="tc-msgs" role="log" aria-live="polite" aria-relevant="additions" aria-label="${esc(tr('Messages'))}">${tcMsgsHtml()}</div>
    ${replyBarHtml('t:' + rid)}<div class="chcomp tccomp"><div class="mpick hidden" role="listbox" aria-label="${esc(tr('Mention someone'))}"></div><textarea id="tc-in" rows="1" name="kalmido-team-message" autocomplete="off" data-form-type="other" data-lpignore="true" placeholder="${esc(tr('Message to {0}…', name.length > 18 ? name.slice(0, 17).trimEnd() + '…' : name))}" aria-label="${esc(tr('Message to {0}…', name))}" enterkeyhint="send" maxlength="8000">${esc(S.drafts['team:' + rid] || '')}</textarea>
    <button type="button" class="btn pri" data-act="tc-send">${ic('send', 's')}<span>${tr('Send')}</span></button></div>`;
}
function tcMsgsHtml() {
  if (S.tc.err && !S.tc.msgs.length) return `<div class="muted mhint" data-k="err">${esc(S.tc.err)}</div>`;
  if (!S.tc.room) return `<div class="muted mhint" data-k="ld">${tr('Loading…')}</div>`;
  if (!S.tc.msgs.length) return `<div class="muted cmempty" data-k="empty">${tr('No messages yet. Say hello.')}</div>`;
  const U = S.tc.users, ags = new Set((S.tc.room.members || []).filter(m => m.agent).map(m => m.id));
  let prev = null, h = S.tc.more ? `<div class="chold" data-k="older"><button type="button" class="btn sm" data-act="tc-older">${tr('Load older messages')}</button></div>` : '';
  for (const m of S.tc.msgs) {
    const mine = m.user_id === S.me?.id, first = !prev || prev.user_id !== m.user_id || Date.parse(m.created_at) - Date.parse(prev.created_at) > 10 * 60000;
    prev = m;
    const rxr = rxRow(m.reactions || [], {mid: m.id, act: 'tc-react', dis: !!m.deleted || S.tc.edit === m.id, own: mine, key: 't' + m.id});  // 2.18.0 (#651), 2.23.0 (#823)
    const body = m.deleted ? `<div class="cbub del"><span class="muted">${tr('Message deleted')}</span></div>`
      : S.tc.edit === m.id ? `<div class="cbub tcedit"><div class="mpick hidden" role="listbox" aria-label="${esc(tr('Mention someone'))}"></div><textarea class="tc-edit" aria-label="${esc(tr('Edit message'))}" rows="2">${esc(m.body.replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, U)))}</textarea><div class="tcebtn"><button type="button" class="btn sm" data-act="tc-edit-cancel">${tr('Cancel')}</button><button type="button" class="btn sm pri" data-act="tc-edit-save" data-mid="${m.id}">${tr('Save')}</button></div></div>`
        : `${replyQuoteHtml(m, 't')}<div class="cbub">${commentBody(m.body, U)}</div>`;  // 2.33.0 (#1076): the quote of the answered message
    h += `<div class="cmsg ${mine ? 'me' : 'ag'} ${first ? 'first' : ''}${rxShow('t' + m.id)}" data-k="m${m.id}" data-mid="t:${m.id}">
      ${first && !mine ? `<div class="tcwho">${av(m.user_id, uname(m.user_id, U), 'avatar sm')}<b>${esc(uname(m.user_id, U))}</b>${ags.has(m.user_id) ? agentBadge() : ''}</div>` : ''}
      ${body}${m.task ? `<button class="runtask" data-act="open-id" data-id="${m.task.id}">${ic('arrow', 's')}<span>${esc(m.task.title)}</span></button>` : ''}
      <div class="cmeta"><time title="${esc(fmtWhen(m.created_at))}">${fmtWhen(m.created_at)}</time>${m.edited_at && !m.deleted ? `<span class="muted">${tr('edited')}</span>` : ''}${rxr}${m.deleted || S.tc.edit === m.id ? '' : replyBtn('chrbtn mreply')}${mine && !m.deleted ? `<button type="button" class="rx rxtog" data-act="tc-msg-menu" data-mid="${m.id}" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button>` : ''}</div></div>`;
  }
  return h;
}
// patch the open conversation in place (keeps the box, its text and the keyboard)
function tcPatch(bottom) {
  const box = $('#tc-msgs'); if (!box) return;
  const near = bottom || box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  setHtml(box, tcMsgsHtml());
  if (near) box.scrollTop = box.scrollHeight;
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
  const text = ta.value.trim(); if (!text) return;
  const hadF = document.activeElement === ta;
  if (!S.tc.room) { try { await loadRoom(rid); } catch { /* sent without the mention lookup */ } }  // 2.24.0: @names need the members
  let m;
  const rto = replyTo('t:' + rid);  // 2.33.0 (#1076)
  try { m = await rawFetch('POST', `/api/team/rooms/${rid}/messages`, {body: tcMentions(text), ...(rto ? {reply_to: rto} : {})}); }
  catch (e) { toast(e instanceof Offline ? tr('You are offline: the message was not sent and stays in the box') : e.message); return; }
  ta.value = ''; delete S.drafts['team:' + rid]; autosize(ta); replySent('t:' + rid);
  S.tc.msgs.push(m);
  const r = (S.tc.rooms || []).find(x => x.id === rid); if (r) { r.last = {id: m.id, user_id: m.user_id, text, created_at: m.created_at}; r.last_at = m.created_at; }
  tcPatch(true);
  if (hadF || !isTouch()) ta.focus({preventScroll: true});
}
async function tcReact(mid, emoji) {
  let r; try { r = await rawFetch('POST', `/api/team/messages/${mid}/reactions`, {emoji}); } catch (e) { toast(e.message); return; }
  const m = S.tc.msgs.find(x => x.id === mid); if (m) m.reactions = r.reactions;
  tcPatch(); rxRefocus('#tc-msgs', mid, emoji);
}
function tcMsgMenu(anchor, mid) {
  const m = S.tc.msgs.find(x => x.id === mid); if (!m) return;
  menu(anchor, [{label: tr('Reply'), icon: 'reply', fn: () => replyStart('t', mid)}, {label: tr('Edit'), icon: 'edit', fn: () => { S.tc.edit = mid; tcPatch(); setTimeout(() => { const t = $('#tc-msgs .tc-edit'); if (t) { t.focus(); autosize(t); } }, 0); }},
    {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => tcMsgDelete(mid)}]);
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
  // text box, Delete: the focus goes to the message box)
  if (!v) { if (await tcMsgDelete(mid)) $('#tc-in')?.focus(); else $('#tc-msgs .tc-edit')?.focus(); return; }
  let r; try { r = await rawFetch('PATCH', `/api/team/messages/${mid}`, {body: tcMentions(v)}); } catch (e) { toast(e.message); return; }
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
  if (!S.tc.people.length && !quiet.length) { dmWhy(); return; }  // 2.24.0 (#906): the button is always there and explains why not yet
  menu(anchor, [...S.tc.people.map(p => ({label: p.name, icon: 'user', fn: () => dmOpen(p.id, p.name)})),
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
// the open conversation follows the route; switching rooms loads it
function teamRoute(rid) {
  if (S.tc.rid !== rid) { S.tc.rid = rid; S.tc.room = null; S.tc.msgs = []; S.tc.more = false; S.tc.edit = null; if (rid) loadRoom(rid).then(() => { if (S.route.mod === 'team' && S.tc.rid === rid) { renderView(); teamFit(); } }); }
}
document.addEventListener('keydown', e => {
  if (e.target.id === 'tc-in' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); tcSend(); }
  if (e.key === 'Escape' && S.dash?.custom && e.target.closest?.('.dash')) { e.preventDefault(); e.stopPropagation(); $('#view [data-act="dash-done"]')?.click(); return; }  // 2.17.2
  if (e.target.classList?.contains('tc-edit')) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); tcEditSave(S.tc.edit); }
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
  else return;
  e.preventDefault(); e.stopPropagation();
});
// a shared list's own chat, from its header / menu
async function listChat(lid) {
  if (!teamOn()) return;
  if (S.tc.rooms === null) await loadTeam();
  const r = (S.tc.rooms || []).find(x => x.kind === 'list' && x.list_id === lid);
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
  return html.replace(/<(\/?)([a-zA-Z][\w-]*)[^>]*>|(?<![&\w/#])#(\d{1,9})\b/g, (m, cl, tag, id) => {
    if (tag) { if (/^(code|a|pre|button)$/i.test(tag)) skip = Math.max(0, skip + (cl ? -1 : 1)); return m; }
    if (skip > 0) return m;
    const t = taskById(+id); if (!t) return m;  // not visible to me: stays text (no title leaks)
    return trefHtml(t, compact);
  });
}
const trefHtml = (t, compact) => `<a href="#t/${t.id}" class="tref" data-tref="${t.id}" title="${esc(t.title)}">#${t.id}${compact ? '' : ' ' + esc(t.title.slice(0, 60))}</a>`;
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
  if (S.nt.lid !== lid) { S.nt = {...S.nt, lid, notes: null, err: null}; loadNotes(lid).then(() => { if (S.route.mod === 'notes') renderView(); }); }
  if (S.nt.id !== id) { noteFlush(); S.nt.id = id; S.nt.edit = !!id && S.nt.newId === id; S.nt.newId = null; }
}
function viewNotes() {
  const l = listById(S.nt.lid);
  if (!l) return heronEmpty('empty', tr('This list does not exist (any more).'));
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
      : q ? `<div class="empty">${tr('No notes match.')}</div>` : heronEmpty('empty', tr('No notes yet.'), S.nt.mayWrite ? tr('Meeting notes, briefings, decisions: write them next to the tasks.') : '')}`;
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
    ...(others.length ? [{label: tr('Move to list…'), icon: 'folder', fn: () => menu(anchor, others.map(l => ({label: lname(l), fn: async () => {
      try { const r = await rawFetch('PATCH', `/api/notes/${n.id}`, {list_id: l.id}); Object.assign(n, r); } catch (e) { toast(e.message); return; }
      await load(); toast(tr('Moved to {0}', lname(l))); go('note/' + n.id); }})))}] : []),
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
    setHtml(r, ntCardsHtml(vis, q, S.nt.id && ns.find(n => n.id === S.nt.id)));
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
const MSG_KIND = {task: N_('Comment'), list: N_('Team chat'), dm: N_('Direct message'), agent: N_('Agent chat')};
const msgIcon = h => h.chat_type === 'agent' ? 'bot' : h.chat_type === 'list' ? 'users' : h.chat_type === 'dm' ? 'user' : 'comment';
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
function msgSecDraw() { const el = $('#smsgs'); if (el) el.innerHTML = msgSecHtml(); }
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
