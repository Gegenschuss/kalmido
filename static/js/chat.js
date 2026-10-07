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
const editingTeam = () => document.activeElement?.id === 'tc-in' || document.activeElement?.classList?.contains('tc-edit');
const roomName = r => r ? (r.kind === 'dm' ? (r.name || '?') : lname(listById(r.list_id)) || r.name || '?') : '';
const roomIcon = r => r.kind === 'dm' ? av(r.user_id, r.name, 'avatar') : `<span class="tcico">${licon(listById(r.list_id), 'licon') || ic('users', 's')}</span>`;
function viewTeam() {
  if (!teamOn()) return `<div class="empty">${tr('The team chat needs collaboration (Settings > Modules).')}</div>`;
  if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.route.mod === 'team') renderView(); }); }
  const rid = S.tc.rid, rooms = S.tc.rooms || [];
  const list = `<nav class="tclist" aria-label="${esc(tr('Conversations'))}">
    <div class="tchead"><b>${tr('Conversations')}</b><span class="spacer"></span><button type="button" class="btn sm pri" data-act="tc-new" aria-haspopup="${S.tc.people.length ? 'menu' : 'dialog'}">${ic('plus', 's')}${tr('New message')}</button></div>
    ${S.tc.rooms === null ? `<div class="muted mhint">${tr('Loading…')}</div>` : rooms.length ? rooms.map(r => `<button type="button" class="tcrow ${r.id === rid ? 'on' : ''} ${r.unread ? 'unread' : ''}" data-act="tc-open" data-rid="${r.id}" ${r.id === rid ? 'aria-current="true"' : ''}>
      ${roomIcon(r)}<span class="tcmain"><span class="tcn">${esc(roomName(r))}${r.kind === 'list' ? `<span class="tck">${ic('users', 's')}${r.members}</span>` : ''}</span>
      <span class="tclast">${r.last ? esc((r.last.user_id === S.me?.id ? tr('You') + ': ' : r.kind === 'list' ? uname(r.last.user_id, S.tc.users) + ': ' : '') + mdBrief(r.last.text)) : `<span class="muted">${tr('No messages yet')}</span>`}</span></span>
      <span class="tcside">${r.last_at ? `<time>${esc(relTime(r.last_at))}</time>` : ''}${r.unread ? `<span class="nbadge ${r.mention ? 'ment' : ''}" aria-label="${esc(trn('{0} unread', '{0} unread', r.unread))}">${r.mention ? '@' : ''}${r.unread}</span>` : ''}${r.muted ? `<span class="tcmute" title="${esc(tr('Muted'))}">${ic('belloff', 's')}</span>` : ''}</span></button>`).join('')
    : `<div class="empty tcempty">${heron('empty')}<b>${tr('No conversations yet')}</b><span>${S.tc.people.length ? tr('Write to someone you work with, or share a list: every shared list gets its own chat.') : tr('Share a list with someone: every shared list gets its own chat.')}</span></div>`}
  </nav>`;
  return `<div class="tcwrap"><div class="tcview ${rid ? 'inroom' : ''}">${list}${rid ? `<section class="tcroom" aria-label="${esc(roomName(S.tc.room ? {...S.tc.room, name: (rooms.find(x => x.id === rid) || {}).name} : rooms.find(x => x.id === rid)))}">${tcRoomHtml()}</section>` : (isMobile() ? '' : `<section class="tcroom tcnone"><div class="empty">${ic('comment')}<span>${tr('Pick a conversation.')}</span></div></section>`)}</div></div>`;
}
function tcRoomHtml() {
  const rid = S.tc.rid, r = (S.tc.rooms || []).find(x => x.id === rid), room = S.tc.room;
  const name = roomName(r || room);
  const head = `<div class="tcrhead"><button type="button" class="iconbtn tcback" data-act="tc-back" aria-label="${esc(tr('Back'))}">${ic('back')}</button>
    ${r ? roomIcon(r) : ''}<div class="tcrt"><b>${esc(name)}</b>${room && room.kind === 'list' ? `<span class="muted">${esc(room.members.map(m => m.name).slice(0, 6).join(', '))}${room.members.length > 6 ? ' +' + (room.members.length - 6) : ''}</span>` : ''}</div>
    <span class="spacer"></span>${room && room.kind === 'list' ? `<button type="button" class="iconbtn" data-act="tc-list" data-id="${room.list_id}" title="${esc(tr('Open the list'))}" aria-label="${esc(tr('Open the list'))}">${ic('list')}</button>` : ''}
    <button type="button" class="iconbtn ${room?.muted ? 'on' : ''}" data-act="tc-mute" aria-pressed="${!!room?.muted}" title="${esc(room?.muted ? tr('Muted: only mentions notify you') : tr('Mute (only mentions notify you)'))}" aria-label="${esc(tr('Mute'))}">${ic(room?.muted ? 'belloff' : 'bell')}</button></div>`;
  return `${head}<div class="chmsgs tcmsgs" id="tc-msgs" role="log" aria-live="polite" aria-relevant="additions" aria-label="${esc(tr('Messages'))}">${tcMsgsHtml()}</div>
    <div class="chcomp tccomp"><div class="mpick hidden" role="listbox" aria-label="${esc(tr('Mention someone'))}"></div><textarea id="tc-in" rows="1" name="kalmido-team-message" autocomplete="off" data-form-type="other" data-lpignore="true" placeholder="${esc(tr('Message to {0}…', name.length > 18 ? name.slice(0, 17).trimEnd() + '…' : name))}" aria-label="${esc(tr('Message to {0}…', name))}" enterkeyhint="send" maxlength="8000">${esc(S.drafts['team:' + rid] || '')}</textarea>
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
        : `<div class="cbub">${commentBody(m.body, U)}</div>`;
    h += `<div class="cmsg ${mine ? 'me' : 'ag'} ${first ? 'first' : ''}${rxShow('t' + m.id)}" data-k="m${m.id}" data-mid="${m.id}">
      ${first && !mine ? `<div class="tcwho">${av(m.user_id, uname(m.user_id, U), 'avatar sm')}<b>${esc(uname(m.user_id, U))}</b>${ags.has(m.user_id) ? agentBadge() : ''}</div>` : ''}
      ${body}${m.task ? `<button class="runtask" data-act="open-id" data-id="${m.task.id}">${ic('arrow', 's')}<span>${esc(m.task.title)}</span></button>` : ''}
      <div class="cmeta"><time title="${esc(fmtWhen(m.created_at))}">${fmtWhen(m.created_at)}</time>${m.edited_at && !m.deleted ? `<span class="muted">${tr('edited')}</span>` : ''}${rxr}${mine && !m.deleted ? `<button type="button" class="rx rxtog" data-act="tc-msg-menu" data-mid="${m.id}" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button>` : ''}</div></div>`;
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
  try { m = await rawFetch('POST', `/api/team/rooms/${rid}/messages`, {body: tcMentions(text)}); }
  catch (e) { toast(e instanceof Offline ? tr('You are offline: the message was not sent and stays in the box') : e.message); return; }
  ta.value = ''; delete S.drafts['team:' + rid]; autosize(ta);
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
  menu(anchor, [{label: tr('Edit'), icon: 'edit', fn: () => { S.tc.edit = mid; tcPatch(); setTimeout(() => { const t = $('#tc-msgs .tc-edit'); if (t) { t.focus(); autosize(t); } }, 0); }},
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
  if (!S.tc.people.length) { dmWhy(); return; }  // 2.24.0 (#906): the button is always there and explains why not yet
  menu(anchor, S.tc.people.map(p => ({label: p.name, fn: () => dmOpen(p.id, p.name)})));
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
// #123 -> a link to that task (only tasks I see; text inside code / links stays)
function mdTaskRefs(html) {
  let skip = 0;
  return html.replace(/(<\/?(?:code|a|pre|button)\b[^>]*>)|#(\d{1,9})\b/g, (m, tag, id) => {
    if (tag) { skip += tag[1] === '/' ? -1 : 1; return m; }
    if (skip > 0) return m;
    const t = taskById(+id); if (!t) return m;
    return `<a href="#t/${t.id}" class="tref" title="${esc(t.title)}">#${t.id} ${esc(t.title.slice(0, 60))}</a>`;
  });
}
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
