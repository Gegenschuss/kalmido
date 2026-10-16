// ---- 2.62.0 (#1530): sending in the team chat and the agent chat. A message shows at once as "Sending…" at the end of
// the conversation and the box empties; Send and Enter wait until the server answered (one message in flight per
// conversation), an error puts the text back into the box. Every message carries client_id (the same on a retry): the
// server answers a second send within seconds with the first message. Waking the device (visible again / online again)
// fetches the open conversations at once instead of waiting for the next change check.
const CSD = {pend: {}};  // conversation key ('t:<room>' | 'a:<agent>') -> [{cid, text, last}]
function csdCid() { return globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2, 10); }
function csdBusy(k) { return !!(CSD.pend[k] || []).length; }
function csdAdd(k, text, msgs) { const p = {cid: csdCid(), text, last: msgs.length ? msgs[msgs.length - 1].id : 0}; (CSD.pend[k] = CSD.pend[k] || []).push(p); return p; }
function csdDone(k, p) { CSD.pend[k] = (CSD.pend[k] || []).filter(x => x !== p); if (!CSD.pend[k].length) delete CSD.pend[k]; }
// the waiting bubbles of conversation k (one that a refresh already brought along as a real message stays hidden)
function csdHtml(k, msgs, mine) {
  return (CSD.pend[k] || []).filter(p => !msgs.some(m => m.id > p.last && mine(m) && (m.body || '').trim() === p.text)).map(p =>
    `<div class="cmsg me csdpend" data-k="p${esc(p.cid)}" aria-busy="true"><div class="cbub">${commentBody(p.text, {})}</div><div class="cmeta"><span class="muted">${tr('Sending…')}</span></div></div>`).join('');
}
// the box after a failed send: the text comes back (in front of anything typed meanwhile)
function csdBack(ta, text, dk) {
  if (!ta || !ta.isConnected) { S.drafts[dk] = text; return; }
  ta.value = ta.value.trim() ? text + '\n' + ta.value : text; S.drafts[dk] = ta.value; autosize(ta);
}
function csdWake() {
  if (document.hidden) return;
  if (S.chat?.aid && collab()) chatLoad();
  if (S.tc?.rid && typeof teamChanged === 'function') teamChanged();
}
document.addEventListener('visibilitychange', csdWake);
window.addEventListener('online', () => setTimeout(csdWake, 300));
