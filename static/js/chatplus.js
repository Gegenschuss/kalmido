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

// ---- 2.62.0 (#1848): pinned chat messages (team chat and agent chat). "Pin" / "Unpin" in a message's menu (next to
// Reply; phones: press and hold) puts it into the bar above the messages: the newest pin, "1/3" and an arrow through the
// others when there are several, a tap on the text jumps to the message (msgJump also loads older pages), the x unpins.
// At most 5 per conversation (the server says so). One Undo step per pin / unpin. The pins come with every load of the
// conversation (also when older than the loaded page): S.tc.pins / S.chat.pins.
const CPN = {};
const cpnPins = k => k[0] === 't' ? (S.tc?.rid === +k.slice(2) ? S.tc.pins || [] : []) : (S.chat?.aid === +k.slice(2) ? S.chat.pins || [] : []);
function cpnText(m, art) {
  let body = m.body || '';
  if (art === 't' && m.enc) {  // an encrypted DM: the text this browser decrypted (the server has only the ciphertext)
    const d = (S.tc.msgs || []).find(x => x.id === m.id && x._dec) || null;
    body = d ? d.body : (typeof E2E !== 'undefined' && E2E.dec?.[m.id + ':' + (m.edited_at || '')]) || '';
    if (!body) return tr('Encrypted message');
  }
  const t = mdBrief(decodeMentions(body, art === 't' ? S.tc.users || {} : {})) || (m.attachments || [])[0]?.name || '';
  return t.length > 140 ? t.slice(0, 140) + '…' : t;
}
// 2.82.0 (#1862): the conversation of the open pin / unpin Undo toast is no longer on screen: close the toast (it would hit
// that conversation unseen). Checked after the bars are drawn, so a side chat window keeps its Undo
function cpnUndoDrop() {
  if (!CPN.undoK || document.querySelector(`[data-cpn="${cssEsc(CPN.undoK)}"]`)) return;
  if (HIST.toastE === CPN.undoE) { HIST.toastE = null; $('#toast')?.classList.add('hidden'); }
  CPN.undoK = CPN.undoE = null;
}
function cpnBarHtml(k) {
  const pins = cpnPins(k), art = k[0];
  if (!pins.length) return `<div class="cpnbar" data-cpn="${k}" hidden></div>`;
  // 2.87.9 (#1909): every pin in its own line (sender + text), 1-2 as they are, from 3 on the bar stays two lines high and scrolls
  const who = m => art === 't' ? uname(m.user_id, S.tc.users || {}) : m.from === 'agent' ? agentById(S.chat?.aid)?.name || tr('Agent') : tr('You');
  const row = m => `<div class="cpnrow"><button type="button" class="cpngo" data-act="cpn-go" data-art="${art}" data-id="${m.id}" title="${esc(tr('Show the message'))}"><b>${esc(who(m))}</b><span>${esc(cpnText(m, art))}</span></button><button type="button" class="iconbtn cpnx" data-act="cpn-x" data-art="${art}" data-id="${m.id}" title="${esc(tr('Unpin'))}" aria-label="${esc(tr('Unpin'))}">${ic('x', 's')}</button></div>`;
  return `<div class="cpnbar" data-cpn="${k}" role="region" aria-label="${esc(tr('Pinned messages'))}">${ic('pin', 's')}<div class="cpnlist ${pins.length > 2 ? 'scr' : ''}">${pins.map(row).join('')}</div></div>`;
}
// the bars on the screen follow the state (called by tcPatch / chatPatch and after a pin)
function cpnSync() {
  for (const el of document.querySelectorAll('[data-cpn]')) { const h = cpnBarHtml(el.dataset.cpn); if (!wk_sameEl(el, h)) {  /* 2.119.1 D (#2310): a freshly drawn bar has no _h yet */ const t = document.createElement('template'); t.innerHTML = h; const n = t.content.firstElementChild; n._h = h; el.replaceWith(n); } }
  cpnUndoDrop();
}
// the small pin in a pinned message's line
const cpnMark = m => m.pinned_at && !m.deleted ? `<span class="cpnmark" title="${esc(tr('Pinned'))}" aria-label="${esc(tr('Pinned'))}">${ic('pin', 's')}</span>` : '';
const cpnItem = (art, m) => ({label: m.pinned_at ? tr('Unpin') : tr('Pin'), icon: 'pin', fn: () => cpnToggle(art, m.id, !m.pinned_at)});
async function cpnSet(art, place, id, on) {
  const url = art === 't' ? `/api/team/messages/${id}/pin` : `/api/agents/${place}/chat/${id}/pin`;
  const r = await rawFetch('POST', url, {pinned: on});
  if (art === 't' && S.tc.rid === place) {
    S.tc.pins = r.pins || []; const m = S.tc.msgs.find(x => x.id === id); if (m) Object.assign(m, {pinned_at: r.message.pinned_at, pinned_by: r.message.pinned_by});
    tcPatch();
  } else if (art === 'a' && S.chat.aid === place) {
    S.chat.pins = r.pins || []; const m = S.chat.msgs.find(x => x.id === id); if (m) Object.assign(m, {pinned_at: r.message.pinned_at, pinned_by: r.message.pinned_by});
    S.chat.mutAt = (S.chat.seq || 0) + 1;  // a refresh that started before this answer fetches again
    chatPatch({keep: true});
  }
  cpnSync();
  return r;
}
async function cpnToggle(art, id, on) {
  const place = art === 't' ? S.tc.rid : S.chat.aid, k = art + ':' + place;
  try { await cpnSet(art, place, id, on); } catch (e) { toast(e instanceof Offline ? tr('Only available online.') : e.message); return; }
  const e = histAdd({label: on ? tr('Message pinned') : tr('Message unpinned'), undo: () => cpnSet(art, place, id, !on), redo: () => cpnSet(art, place, id, on)});
  offerUndo(on ? tr('Message pinned') : tr('Message unpinned'), e);
  CPN.undoK = k; CPN.undoE = e;
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="cpn-go"],[data-act="cpn-x"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const art = a.dataset.art, id = +a.dataset.id;
  if (a.dataset.act === 'cpn-x') { cpnToggle(art, id, false); return; }
  msgJump({art, id, chat: art === 't' ? S.tc.rid : null, agent: art === 'a' ? S.chat.aid : null});
});
