/* Kalmido web client: a chat in its own small browser window (2.46.2, #1719).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// Desktop, like a list (miniwin.js, #1294): the button "Open in its own window" in the header of an agent chat, a team room or
// a direct message, or a middle click on a conversation / an agent's Chat button / a link to a chat, opens /?mini=1#agents/<id>
// or /?mini=1#team/<id> in a narrow window (one window name per chat: the same chat comes back to its window). The window
// shows only this conversation (no sidebar, tabs, list of conversations, Back), live like any tab; the miniwin.js guards keep
// its UI state (local preferences, settings PATCHes) to itself. Touch devices: nothing changes (no button, no middle click).
const dw_chatOf = h => { const m = /^#(agents|team)\/(\d+)/.exec(h || ''); return m ? `${m[1]}/${+m[2]}` : ''; };
const DW_CHAT = MW_ON ? dw_chatOf(location.hash) : '';
const dw_chatMini = () => !!DW_CHAT;  // agentchat.js chatFull(): the window's chat is always the full page, at any width
function dw_chatOpen(kind, id) {
  id = +id; if (!id || !['agents', 'team'].includes(kind)) return null;
  const w = Math.min(440, screen.availWidth || 440), h = Math.min(720, screen.availHeight || 720);
  const x = Math.max(0, (window.screenX || 0) + (window.outerWidth || 0) - w - 40), y = Math.max(0, (window.screenY || 0) + 60);
  const win = window.open(`/?mini=1#${kind}/${id}`, `kalmido-chat-${kind === 'agents' ? 'a' : 't'}-${id}`, `popup,width=${w},height=${h},left=${x},top=${y}`);
  if (!win) { toast(tr('The browser blocked the window. Allow pop-ups for this page.')); return null; }
  try { win.focus(); } catch { /* another origin / closed */ }
  return win;
}
// the button in a chat's header (agentchat.js chatWinBtns, chat.js tcRoomHtml): desktop main window only
const dw_winBtn = (kind, id) => mw_ok() && id ? `<button type="button" class="iconbtn" data-dwchat="${kind}/${+id}" title="${esc(tr('Open in its own window'))}" aria-label="${esc(tr('Open in its own window'))}">${ic('panel', 's')}</button>` : '';
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-dwchat]'); if (!b || !mw_ok()) return;
  e.preventDefault(); e.stopPropagation();
  const [k, id] = b.dataset.dwchat.split('/'); dw_chatOpen(k, id);
}, true);
// middle click: a conversation in the team chat, an agent's Chat button, a link to a chat (Home, News, the agents' cards)
const dw_target = e => {
  const r = e.target.closest?.('#view .tcrow[data-rid], [data-act="chat-open"][data-aid], a[href^="#agents/"], a[href^="#team/"]'); if (!r) return null;
  if (r.dataset.rid) return ['team', +r.dataset.rid];
  if (r.dataset.aid) return ['agents', +r.dataset.aid];
  const h = r.getAttribute('href'); if (!/^#(agents|team)\/\d+(?:$|\?)/.test(h || '')) return null;  // not a sub page of the chat
  const k = dw_chatOf(h); return k ? k.split('/') : null;
};
document.addEventListener('mousedown', e => { if (e.button === 1 && mw_ok() && dw_target(e)) e.preventDefault(); });  // no auto-scroll
document.addEventListener('auxclick', e => {
  const t = e.button === 1 && mw_ok() && dw_target(e); if (!t) return;
  e.preventDefault(); dw_chatOpen(t[0], t[1]);
});
if (DW_CHAT) {
  document.documentElement.classList.add('mini-chat');
  // only this chat (a task opened from it may show): another view's address goes back to the chat
  window.addEventListener('hashchange', () => { if (dw_chatOf(location.hash) !== DW_CHAT && !/^#t\//.test(location.hash)) location.replace('#' + DW_CHAT); });
  // the window's title: the agent's / the conversation's name
  const [k, id] = DW_CHAT.split('/');
  const title = () => {
    if (!S.booted) return;
    const n = k === 'agents' ? agentById(+id)?.name : roomName((S.tc.rooms || []).find(r => r.id === +id) || (S.tc.rid === +id ? S.tc.room : null));
    if (n && n !== '?' && document.title !== `${n} · ${APP_NAME}`) document.title = `${n} · ${APP_NAME}`;
  };
  setTimeout(title, 300); setInterval(title, 2000);
}
