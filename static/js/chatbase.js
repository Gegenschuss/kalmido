/* Kalmido web client: the parts of the agent chat that code loaded at start uses (2.65.0, #1823). The chat itself
   (agentchat.js with agentsetup.js) loads on demand (lazyload.js LD_MODS.agentchat): these stay -- the phone / desktop
   switch, the pop-up button, the reaction rows of comments and the team chat, patchKids, the task panel's usage line.
   Moved unchanged from agentchat.js. Classic script sharing the global scope with the others (load order: index.html,
   docs/ARCHITECTURE.md). */
'use strict';
const chatFull = () => isMobile() || innerWidth < 1000 || (typeof dw_chatMini === 'function' && dw_chatMini());  // 2.46.2 (#1719): the chat's own window (chatwin.js)
S.chat = {aid: null, msgs: [], err: null};
// ---- 2.29.0 (#363) desktop: the chat as a pop-up window from anywhere -- the round button bottom right (the agent last
// chatted with), the key A and "Chat as a window" in the command bar. The window stays open while you switch lists and views,
// can be moved by its header, folded to the header and docked as the side panel again (remembered per device: chatFloat).
const chatFloatOn = () => !chatFull() && LS.get('chatFloat', '') === '1';
function chatFabAgent() {
  const ags = (S.agents || []).filter(a => a.enabled && a.chat !== false), last = +LS.get('chatLast', 0);
  return ags.find(a => a.id === last) || ags[0] || null;
}
function chatFabDraw() {
  let b = $('#chatfab');
  const a = S.booted && !chatFull() && feat('agents') && LS.get('chatFab', '1') !== '0' ? chatFabAgent() : null;
  // 2.223.0 A (#2815): body.fab-on = the button is there, docked composers keep its corner free (app.css --fab-safe)
  const on = !!a && !(!$('#achat')?.classList.contains('hidden') && $('#achat'));
  document.body.classList.toggle('fab-on', on);
  if (!on) { b?.remove(); return; }
  if (!b) { b = document.createElement('button'); b.id = 'chatfab'; b.type = 'button'; b.dataset.act = 'chat-pop'; document.body.appendChild(b); }
  const t = tr('Chat with {0}', a.name);
  b.title = t + ' (A)'; b.setAttribute('aria-label', t);
  b.innerHTML = av(a.id, a.name, 'avatar') + (a.chat_unread || a.approvals_open ? `<span class="nbadge${a.approvals_open ? ' apvn' : ''}">${(a.chat_unread || 0) + (a.approvals_open || 0)}</span>` : '');
}
const apvCount = n => trn('{0} approval open', '{0} approvals open', n);
// 2.7.2 (#421): reactions on a chat message. 2.13.0 (#453 A2): the quick 👍 / 👎 / ❤️ no longer sit as three empty circles
// under every agent message: they appear on hover / keyboard focus (desktop) or a long press (touch) as a small bar over the
// bubble's corner. Only an agent message that asks something (m.asks, server: chat_asks) counts a 👍 / 👎 as approval /
// rejection: there the newest unanswered question shows the bar right away with the hint "👍 = approval", and a given 👍 / 👎
// says "Counted as approval / rejection". Existing reactions always show as pills; on mine only what the agent reacted with.
// the open quick bar is state (S.rxOpen = 'c<chat msg id>' | 'k<comment id>' | 't<team msg id>'), so a re-render (the chat
// polls, a reaction arrives) keeps it open instead of closing it under the finger
S.rxOpen = null;
const rxTog = (key = null) => `<button type="button" class="rx rxtog" data-act="rx-tog" aria-expanded="${!!key && S.rxOpen === key}" title="${esc(tr('React'))}" aria-label="${esc(tr('React'))}">${ic('smile', 's')}</button>`;
const rxShow = key => S.rxOpen === key ? ' rxshow' : '';
const rxKey = host => host.classList.contains('cm') ? 'k' + host.dataset.cid : (host.closest('#tc-msgs') ? 't' : 'c') + String(host.dataset.mid).split(':').pop();
// 2.18.0 (#651, owner decision: reactions not hidden behind a smiley, too many taps): the quick reactions 👍 👎 ❤️ sit visibly in the
// meta line of every chat message (agent chat and team chat, my own messages too); one tap toggles mine, the number says
// how many reacted. Calm: an unused chip is only its muted emoji. Touch: 44 px targets through negative margins (the line
// stays low). One Tab stop per message: a roving tabindex, ← → Home End move inside the row (rxRowKey).
// dis = read-only (a paused agent, a deleted message): only the reactions that exist, as disabled chips.
// name(k, meaning) = the label of a quick chip (the agent chat names 👍 / 👎 on a question as approval / rejection)
const RXN = {up: N_('thumbs up'), down: N_('thumbs down'), heart: N_('heart')};
// 2.23.0 (#823, owner decision): no reactions on one's own message (own: only the reactions of others, read-only); the quick
// reactions of other people's messages sit behind a smiley button again (key: the open row, S.rxOpen), except keep (👍 / 👎
// on an open question of an agent: the approval stays one tap away)
function rxRow(rs, {mid, act, dis = false, name = null, extra = '', own = false, key = null, keep = [], hide = []}) {
  const meIn = r => !!r && (r.users || []).some(u => S.me && u.id === S.me.id), cnt = r => r ? r.count ?? (r.users || []).length : 0;
  if (own) dis = true;
  const items = RX.filter(x => !hide.includes(x[0])).map(([k, em, n]) => { const o = name ? name(k, n) : n; return {k, em, n, o: o !== n ? o : '', r: rs.find(r => r.emoji === k)}; }).filter(x => !dis || cnt(x.r));
  for (const r of rs) if (!RX.some(x => x[0] === r.emoji) && cnt(r)) items.push({k: r.emoji, em: rxEmoji(r.emoji), n: '', r});
  if (!items.length && !extra) return '';
  const fi = Math.max(0, items.findIndex(x => meIn(x.r)));
  const chip = (x, i) => {
    const me = meIn(x.r), c = cnt(x.r), who = c ? x.r.users.map(u => u.name).join(', ') : '';
    const base = x.o ? tr(x.o) : RXN[x.k] ? tr('React with {0}', tr(RXN[x.k])) : x.em;
    const lab = base + (who ? ': ' + who : ''), tip = (x.o ? tr(x.o) : x.n ? tr(x.n) : x.em) + (who ? ' · ' + who : '');
    return `<button type="button" class="rx${c ? '' : ' add'}${me ? ' on' : ''}${!c && key && !keep.includes(x.k) ? ' rxq' : ''}" data-act="${act}" data-mid="${mid}" data-e="${esc(x.k)}" tabindex="${i === fi ? 0 : -1}" title="${esc(tip)}" aria-label="${esc(lab)}" aria-pressed="${me}" ${dis ? 'disabled' : ''}>${esc(x.em)}${c ? `<span class="rxn" aria-hidden="true">${c}</span>` : ''}</button>`;
  };
  // 2.19.0: "+" = more emojis (a small grid), one more stop in the row's arrow keys
  const more = dis ? '' : (key ? rxTog(key) : '') + `<button type="button" class="rx rxplus${key ? ' rxq' : ''}" data-act="rx-more" data-rxact="${act}" data-mid="${mid}" tabindex="-1" aria-haspopup="dialog" title="${esc(tr('More reactions'))}" aria-label="${esc(tr('More reactions'))}">${ic('plus', 's')}</button>`;
  return `<span class="rxbar chrx rxrow" role="group" aria-label="${esc(tr('Reactions'))}">${items.map(chip).join('')}${more}${extra}</span>`;
}
// the arrow keys inside a reaction row (one Tab stop per message)
function rxRowKey(e) {
  const b = e.target.closest?.('.rxrow .rx'); if (!b || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return false;
  const all = $$('.rx:not(:disabled)', b.closest('.rxrow')), i = all.indexOf(b); if (i < 0) return false;
  const j = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
  all.forEach((x, k) => x.tabIndex = k === j ? 0 : -1); all[j].focus(); e.preventDefault(); return true;
}
document.addEventListener('keydown', e => { if (rxRowKey(e)) e.stopPropagation(); }, true);
// after a reaction the row is drawn anew: the focus goes back to the same chip (it was on it, now it is detached)
function rxRefocus(sel, mid, emoji) {
  const ae = document.activeElement; if (ae && ae !== document.body && ae.isConnected) return;
  const b = $$(`${sel} .rxrow .rx[data-mid="${mid}"]`).find(x => x.dataset.e === emoji); if (!b) return;
  $$('.rx', b.closest('.rxrow')).forEach(x => x.tabIndex = x === b ? 0 : -1); b.focus({preventScroll: true});
}
// touch: a long press on an agent message opens its reaction bar (another tap elsewhere closes it)
{
  let lp = null;
  document.addEventListener('touchstart', e => {
    // 2.18.0 (#651): chat messages show their reactions anyway; the long press stays for comments in the task panel
    // 2.32.0 (#1062): an agent chat message too -- its smiley shows only on hover (desktop) or after a long press (touch)
    const m = e.target.closest?.('#detail .cm:not(.cedit), #chat-msgs .cmsg.ag'); if (!m || e.touches.length !== 1 || e.target.closest('button, a, textarea, input')) { lp = null; return; }
    const p = e.touches[0]; lp = {m, x: p.clientX, y: p.clientY, t: setTimeout(() => { $$('.rxshow').forEach(x => x !== m && x.classList.remove('rxshow')); m.classList.add('rxshow'); S.rxOpen = rxKey(m); if (navigator.vibrate) navigator.vibrate(10); lp = null; }, 450)};
  }, {passive: true});
  document.addEventListener('touchmove', e => { if (lp && Math.hypot(e.touches[0].clientX - lp.x, e.touches[0].clientY - lp.y) > 8) { clearTimeout(lp.t); lp = null; } }, {passive: true});
  document.addEventListener('touchend', () => { if (lp) { clearTimeout(lp.t); lp = null; } }, {passive: true});
  document.addEventListener('click', e => { if (!e.target.closest?.('.rxshow .chrxq, .rxshow .cmrxq')) $$('.rxshow').forEach(x => { if (!x.contains(e.target)) { x.classList.remove('rxshow'); if (S.rxOpen === rxKey(x)) S.rxOpen = null; } }); }, true);
}
S.jobSteps = {}; S.jobOpen = {};
// 2.119.1 D (#2310): is el already what html draws? Its outerHTML is not the same text (boolean attributes like hidden come
// back as hidden="", a parked chat window that takes its ids back has them last): compared as nodes, so nothing is swapped needlessly
function wk_sameEl(el, html) {
  if (el._h === html) return true;
  const t = document.createElement('template'); t.innerHTML = html; const n = t.content.firstElementChild;
  return !!n && !n.nextElementSibling && el.isEqualNode(n);
}
const chatNear = box => box.scrollHeight - box.scrollTop - box.clientHeight <= 3 * remPx();
// 2.12.2 (#451): replaces only the children of box that changed, by their key (data-k) or else by position; the box itself,
// its scroll position and anything focused outside of it stay
// 2.138.4 B (#2189): a keyed row with an open edit bubble (.tcedit) that is still being edited stays as it is: the agent
// chat refreshes every 3 s and autosize() gives the textarea a style, so the row never looked equal and the typed text went
// (the team chat only redraws on news and skips that while its editor has the focus)
function patchKids(box, html) {
  const t = document.createElement('template'); t.innerHTML = html;
  const key = n => n.getAttribute('data-k') || (n.hasAttribute('data-cid') ? 'c' + n.getAttribute('data-cid') : null), old = new Map();
  [...box.children].forEach(n => { const k = key(n); if (k) old.set(k, n); });
  const keep = new Set(); let prev = null;
  for (const n of [...t.content.children]) {
    const k = key(n), at0 = prev ? prev.nextElementSibling : box.firstElementChild;
    const o = k ? old.get(k) : at0 && !key(at0) && !keep.has(at0) ? at0 : null;
    let use = n;
    if (o && o.isEqualNode(n)) use = o;
    else if (o && k && o.querySelector('.tcedit') && n.querySelector('.tcedit')) use = o;  // 2.138.4 B (#2189): a message being edited keeps its editor (text, focus, caret)
    else if (o) o.replaceWith(n);
    const at = prev ? prev.nextElementSibling : box.firstElementChild;
    if (at !== use) box.insertBefore(use, at);
    keep.add(use); prev = use;
  }
  [...box.children].forEach(c => { if (!keep.has(c)) c.remove(); });
  [...box.childNodes].forEach(c => { if (c.nodeType === 3) c.remove(); });
}
const TIDY_SHORT = {off: N_('Off'), suggest: N_('Suggest'), auto: N_('Automatically')};
const fmtTok = v => { v = +v || 0; const f = x => x.toLocaleString(LOCALE(), {maximumFractionDigits: 1}); return v >= 1e6 ? tr('{0}M|million, short', f(v / 1e6)) : v >= 1e3 ? tr('{0}k|thousand, short', f(v / 1e3)) : f(v); };
const fmtUsd = v => v === null || v === undefined ? '–' : +v > 0 && +v < .01 ? '<$0.01' : '$' + (+v).toFixed(2);
// the task panel: "Agent usage" of a task agents reported usage for (only on tasks the viewer sees: it comes with the task)
const aiuTaskLine = t => t.ai_usage ? `<label>${tr('Agent usage')}</label><div class="aiuse" title="${esc(tr('Model usage agents reported for this task'))}">${ic('chart', 's')}<span>${esc(tr('{0} tokens', fmtTok(t.ai_usage.tokens)))}${t.ai_usage.cost !== null && t.ai_usage.cost !== undefined ? ' · ' + esc(fmtUsd(t.ai_usage.cost)) : ''} · ${esc(trn('{0} report', '{0} reports', t.ai_usage.calls))}</span></div>` : '';
// 2.65.0 (#1823): the pop-up button follows the window width also before the chat is loaded (agentchat.js redraws it too)
{ let t = 0; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(chatFabDraw, 150); }); }
