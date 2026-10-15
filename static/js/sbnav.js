/* Kalmido web client: the sidebar's messenger rows (2.45.0, #1509).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- #1509: "Messages" on top of "Conversations" (always there while the team chat is on), below it the last conversations
// (direct messages + list channels, at most 5, unread first and bold); every person row has a speech bubble for a direct message
const SB_RECENT = 5;
function sb_rooms() {
  if (!teamOn()) return [];
  if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.tc.rooms !== null) renderSide(); }); }  // failed (offline): the next drawing asks again
  const rs = (S.tc.rooms || []).filter(r => r.last && (r.kind === 'dm' || inWs(listById(r.list_id))));  // newest first (server)
  const un = r => r.unread > 0 && (!r.muted || r.mention);
  return [...rs.filter(un), ...rs.filter(r => !un(r))].slice(0, SB_RECENT);
}
function sb_msgRows() {
  if (!teamOn()) return '';
  const rs = sb_rooms(), rid = S.route.mod === 'team' ? (S.cw?.lt ? S.cw.home?.rid : S.tc.rid) : null, lit = rs.some(r => r.id === rid);  // 2.47c (#1720): the team view's conversation, not one live in the chat panel
  const n = S.team?.unread || 0, lab = tr('Messages');
  const head = `<button class="srow sbmsg ${S.route.mod === 'team' && !lit ? 'on' : ''}" data-go="team" ${isTouch() ? '' : `title="${esc(kt(lab, 'g n'))}"`}>${ic('comment')}<span class="n">${esc(lab)}</span><span class="c ${n ? 'nunread' : ''}">${n ? `${n}<span class="sr"> ${esc(tr('unread'))}</span>` : ''}</span></button>`;
  return head + rs.map(r => {
    const u = r.unread > 0 && (!r.muted || r.mention), nm = roomName(r);
    const ico = r.kind === 'dm' ? av(r.user_id, r.name, 'avatar sbav') : `<span class="sic" aria-hidden="true">${listIconHtml(listById(r.list_id)) || ic('users', 's')}</span>`;
    return `<button class="srow sbconv ${u ? 'sbun' : ''} ${r.id === rid ? 'on' : ''}" data-go="team/${r.id}" title="${esc(r.kind === 'dm' ? tr('Direct message with {0}', nm) : tr('Team chat') + ' · ' + nm)}">${ico}<span class="n">${esc(nm)}</span><span class="c ${u ? 'nunread' : ''}">${r.unread ? `${r.unread}<span class="sr"> ${esc(tr('unread'))}</span>` : ''}</span></button>`;
  }).join('');
}
// a person row: the row opens their tasks (who/<id>), the bubble next to it the direct message
function sb_personRow(p, on) {
  const row = `<button class="srow steam ${on ? 'on' : ''}" data-go="who/${p.id}" title="${esc(tr('Tasks of {0}', p.name))}"><span class="sdot"${ac_mk(p.id)}><i class="pdot"></i></span><span class="n">${esc(p.name)}</span></button>`;
  if (!teamOn()) return row;
  const lab = tr('Message {0}', p.name);
  return `<div class="sbpw">${row}<button type="button" class="iconbtn sbdm" data-sb="dm" data-uid="${p.id}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('comment', 's')}</button></div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-sb="dm"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); closeSide(); dmOpen(+b.dataset.uid, personNameAny(+b.dataset.uid));
}, true);
