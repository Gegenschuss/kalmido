/* Kalmido web client: News and comments + activity (module "collab").
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ News ("Neuigkeiten", module "collab")
// Server feed of what concerns me (mentions, comments on my tasks, assignments, completions, sharing);
// texts are built here from structured items. Unread count + a change marker come with /api/state and
// /api/version, the feed itself is fetched while the view is open (never queued offline).
S.nf = {items: null, users: {}, sig: null, filter: LS.get('newsFilter', '') ? 'me' : '', unread: !!LS.get('newsUnread', false), kind: LS.get('newsKind', '')};  // #302 unread only: per device  // 1.9.0: 'mentions' became 'me' (mentions + assigned to me)
// 2.6.1 (#403): the bell opens the newest News right where I am (desktop: a dropdown under it, phone: a sheet from the
// bottom); "Show all" goes to the full view, a click outside / Esc closes it and I stay in my list
function bellBtn() {
  if (!collab()) return '';
  const n = bellCount();  // 2.28.0 (#987): only what people send me (+ unread direct messages)
  return `<button class="iconbtn bell ${S.route.mod === 'news' ? 'on' : ''}" data-act="bell-pop" aria-haspopup="dialog" title="${esc(tr('News') + ' · ' + newsWhat())}" aria-label="${esc(n ? trn('{0} unread news item', '{0} unread news items', n) : tr('News'))}">${ic('bell')}${n ? `<span class="nbadge">${n > 99 ? '99+' : n}</span>` : ''}</button>`;
}
// 2.6.1 (#404): filter chips (view only, per device): which kinds of News show, in the News view and under the bell
const NEWS_CHIPS = [['mention', 'at', N_('Mentions'), ['mention']], ['comment', 'comment', N_('Comments'), ['comment']],
  ['assign', 'user', N_('Assignments'), ['assign', 'unassign', 'take']], ['newtask', 'plus', N_('New tasks'), ['newtask', 'errreport']],
  ['complete', 'check', N_('Completed'), ['complete', 'unblock']], ['status', 'pulse', N_('Status'), ['status']],
  ['agents', 'bot', N_('Agents'), ['approval', 'proposal', 'usage']], ['share', 'users', N_('Sharing'), ['share', 'role', 'unshare', 'owner']],
  ['followup', 'hourglass', N_('Follow-ups'), ['followup']]];
const newsKindOk = (it, k = S.nf.kind) => { const c = k && NEWS_CHIPS.find(x => x[0] === k); return !c || c[3].includes(it.kind); };
function newsChipsHtml(items, attr) {
  const k = S.nf.kind, have = NEWS_CHIPS.filter(c => c[0] === k || (items || []).some(it => c[3].includes(it.kind)));
  if (!have.length || (have.length === 1 && !k)) return '';
  const da = attr === 'data-nk' ? 'data-act="news-kind"' : '';
  return `<div class="nchips" role="group" aria-label="${esc(tr('Show only'))}"><button type="button" class="nchip ${k ? '' : 'on'}" ${da} ${attr}="" aria-pressed="${!k}">${tr('All')}</button>${have.map(([v, i, n]) => `<button type="button" class="nchip ${k === v ? 'on' : ''}" ${da} ${attr}="${v}" aria-pressed="${k === v}">${ic(i, 's')}${tr(n)}</button>`).join('')}</div>`;
}
function newsKindSet(k) { S.nf.kind = !k || S.nf.kind === k ? '' : k; LS.set('newsKind', S.nf.kind); }
const BELL_N = 8;
// 2.28.0 (#987): the unread direct messages (people writing to me) as rows at the top of "For you"
const dmRows = () => teamOn() ? (S.tc.rooms || []).filter(r => r.kind === 'dm' && r.unread && !r.muted) : [];
const dmRowHtml = r => `<a class="nitem unread k-dm ndm" href="#team/${r.id}" aria-label="${esc(trn('{0} new message from {1}', '{0} new messages from {1}', r.unread, r.name))}">${av(r.user_id, r.name, 'avatar', '', `<i class="nk">${ic('comment', 's')}</i>`)}<div class="nmain"><div class="ntext">${trn('{0} new message from {1}', '{0} new messages from {1}', r.unread, `<b>${esc(r.name)}</b>`)}</div>${r.last ? `<div class="nexc">${esc(mdBrief(r.last.text))}</div>` : ''}</div>${r.last_at ? `<time>${relTime(r.last_at)}</time>` : ''}</a>`;
const newsSecHead = (k, n, first) => `<div class="nsec ${first ? 'first' : ''}">${k === 'me' ? ic('at', 's') : ic('pulse', 's')}<span>${k === 'me' ? tr('For you') : tr('Activity')}</span>${n ? `<span class="c nunread">${n}</span>` : ''}</div>`;
function bellPopHtml() {
  const mine = S.nf.items && S.nf.f === S.nf.filter ? S.nf.items : null, n = bellCount(), nAll = S.news?.unread || 0;
  if (teamOn() && S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; }); }
  const all0 = (mine || []).map((it, i) => [it, i]).filter(([it]) => (!S.nf.unread || !it.read || it.keep) && newsInWs(it));
  const forMe = all0.filter(([it]) => newsForMe(it)), act = all0.filter(([it]) => !newsForMe(it));
  const all = [...forMe, ...act];  // "For you" first, then the activity
  const shown = all.filter(([it]) => newsKindOk(it)).slice(0, BELL_N);
  const dms = dmRows();
  const head = `<div class="bphead"><button type="button" class="bphl" data-bp="news" title="${esc(tr('Show all'))}"><b id="bp-h">${tr('News')}</b><span class="bpchev" aria-hidden="true">›</span></button>${n ? `<span class="bpnew">${esc(trn('{0} new', '{0} new', n))}</span>` : ''}<span class="spacer"></span>${nAll ? `<button type="button" class="btn sm bpread" data-bp="readall" title="${esc(tr('Mark all as read'))}" aria-label="${esc(tr('Mark all as read'))}">${ic('check', 's')}<span>${tr('All read')}</span></button>` : ''}<button type="button" class="iconbtn" data-bp="settings" title="${esc(tr('What shows up here'))}" aria-label="${esc(tr('What shows up here'))}">${ic('gear', 's')}</button></div>`;
  let body;
  if (!mine) body = `<div class="empty bpempty">${S.nf.err === 'offline' ? tr('News are only available online.') : S.nf.err ? esc(S.nf.err) : tr('Loading…')}</div>`;
  else if (!shown.length) body = `<div class="empty bpempty">${ic('bell')}<span>${all.length ? tr('Nothing of this kind.') : S.nf.unread && mine.length ? tr('No unread news') : tr('No news')}</span>${all.length ? '' : `<small class="muted">${esc(newsWhat())}</small>`}</div>`;
  else if (newsBundled()) body = `<div class="nlist bplist nbund">${dms.map(dmRowHtml).join('')}${newsBundledHtml(all.filter(([it]) => newsKindOk(it)).slice(0, 40), true)}</div>`;  // 2.17.0 (#452)
  else {  // 2.28.0 (#987): two sections
    const me_ = shown.filter(([it]) => newsForMe(it)), ac = shown.filter(([it]) => !newsForMe(it));
    body = `<div class="nlist bplist">${dms.length || me_.length ? newsSecHead('me', dms.reduce((a, r) => a + r.unread, 0) + me_.filter(([it]) => !it.read).length, true) + dms.map(dmRowHtml).join('') + me_.map(([it, i]) => newsItemHtml(it, i, true)).join('') : ''}${ac.length ? newsSecHead('act', ac.filter(([it]) => !it.read).length, !dms.length && !me_.length) + ac.map(([it, i]) => newsItemHtml(it, i, true)).join('') : ''}</div>`;
  }
  if (!mine && dms.length) body = `<div class="nlist bplist">${newsSecHead('me', dms.reduce((a, r) => a + r.unread, 0), true)}${dms.map(dmRowHtml).join('')}</div>`;
  const grab = isMobile() ? `<div class="bpgrab" data-bpgrab role="button" tabindex="0" aria-label="${esc(tr('Drag up for more room, tap for full height'))}" title="${esc(tr('Drag up for more room, tap for full height'))}"><i></i></div>`
    : `<button type="button" class="bpgrip" data-bpgrip aria-label="${esc(tr('Resize (arrow keys; double-click: default size)'))}" title="${esc(tr('Drag to resize · double-click: default size'))}"></button>`;
  return `<div class="bpop" role="dialog" aria-labelledby="bp-h">${isMobile() ? grab : ''}${head}${mine ? newsChipsHtml(all.map(x => x[0]), 'data-bpk') : ''}${body}<div class="bpfoot"><button type="button" class="btn pri" data-bp="all">${tr('Show all')}${mine && all.length > shown.length ? ` <span class="bpn">${all.length}</span>` : ''}</button></div>${isMobile() ? '' : grab}</div>`;
}
// ---- 2.7.0: the bell's dropdown is resizable. Desktop: the grip at its bottom-left corner (it hangs right-aligned under
// the bell, so it grows to the left and down), arrow keys on the grip, double-click = the default size. Phone: the
// handle on top of the sheet drags it up to the full height (a tap toggles full / default; dragged far down it closes).
// The size is kept per device (rem, so it follows the font size).
const BELL_MIN = {w: 18, h: 14}, BELL_MAX_W = 48;
const remPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
function bellSize(p) {
  const pop = $('.bpop', p); if (!pop) return;
  const r = remPx();
  if (isMobile()) {
    const h = +LS.get('bellSheetH', 0) || 0, maxH = innerHeight - 8;
    pop.style.height = h ? Math.min(h * r, maxH) + 'px' : ''; pop.style.maxHeight = h ? 'none' : '';
    p.classList.toggle('bpfull', !!h && h * r >= maxH - 2);
    return;
  }
  const sz = LS.get('bellSize', null);
  if (!sz || !(sz.w > 0) || !(sz.h > 0)) { p.style.width = ''; pop.style.height = ''; pop.style.maxHeight = ''; return; }
  const top = p.getBoundingClientRect().top || 60;
  p.style.width = Math.min(sz.w * r, innerWidth - 24) + 'px';
  pop.style.height = Math.max(BELL_MIN.h * r, Math.min(sz.h * r, innerHeight - top - 12)) + 'px'; pop.style.maxHeight = 'none';
}
function bellResizeWire(p, anchor) {
  const pop = () => $('.bpop', p);
  const save = (w, h) => LS.set('bellSize', {w: Math.round(w / remPx() * 100) / 100, h: Math.round(h / remPx() * 100) / 100});
  const apply = (w, h) => {  // desktop: keep the right edge, clamp to the window
    const r = remPx(), right = p.getBoundingClientRect().right, top = p.getBoundingClientRect().top;
    w = Math.max(BELL_MIN.w * r, Math.min(w, BELL_MAX_W * r, right - 12)); h = Math.max(BELL_MIN.h * r, Math.min(h, innerHeight - top - 12));
    p.style.width = w + 'px'; p.style.left = (right - w) + 'px'; pop().style.height = h + 'px'; pop().style.maxHeight = 'none';
    return [w, h];
  };
  p.onpointerdown = e => {
    const grip = e.target.closest?.('[data-bpgrip]'), grab = e.target.closest?.('[data-bpgrab]');
    if (!grip && !grab) return;
    e.preventDefault();
    const x0 = e.clientX, y0 = e.clientY, w0 = p.offsetWidth, h0 = pop().offsetHeight;
    let moved = false, last = [w0, h0];
    try { (grip || grab).setPointerCapture(e.pointerId); } catch { /* old browsers */ }
    const mv = ev => {
      if (Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) > 4) moved = true;
      if (grip) last = apply(w0 - (ev.clientX - x0), h0 + (ev.clientY - y0));
      else { const h = Math.max(BELL_MIN.h * remPx() * .5, Math.min(innerHeight - 8, h0 - (ev.clientY - y0))); pop().style.height = h + 'px'; pop().style.maxHeight = 'none'; last = [0, h]; }
    };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up); removeEventListener('pointercancel', up);
      if (grip) { if (moved) save(...last); return; }
      const r = remPx(), full = innerHeight - 8;
      if (!moved) { const was = +LS.get('bellSheetH', 0); if (was * r >= full - 2) LS.del('bellSheetH'); else LS.set('bellSheetH', Math.round(full / r * 100) / 100); bellSize(p); return; }
      if (last[1] < BELL_MIN.h * r * .75) { closePop(); return; }  // dragged far down: close
      LS.set('bellSheetH', Math.round(Math.min(last[1], full) / r * 100) / 100); bellSize(p);
    };
    addEventListener('pointermove', mv); addEventListener('pointerup', up); addEventListener('pointercancel', up);
  };
  p.ondblclick = e => { if (!e.target.closest?.('[data-bpgrip]')) return; LS.del('bellSize'); bellSize(p); bellPlace(p, anchor); };
  p.addEventListener('keydown', bellGripKey);
}
function bellGripKey(e) {
  const g = e.target.closest?.('[data-bpgrip], [data-bpgrab]'); if (!g) return;
  const p = $('#pop'), pop = $('.bpop', p); if (!pop) return;
  const r = remPx(), step = r * (e.shiftKey ? 4 : 1);
  if (g.dataset.bpgrab !== undefined) {  // phone handle: Enter / Space = full height or back
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault(); const was = +LS.get('bellSheetH', 0); if (was * r >= innerHeight - 10) LS.del('bellSheetH'); else LS.set('bellSheetH', Math.round((innerHeight - 8) / r * 100) / 100); bellSize(p); return;
  }
  const d = {ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowDown: [0, step], ArrowUp: [0, -step]}[e.key];
  if (!d && e.key !== 'Home') return;
  e.preventDefault(); e.stopPropagation();
  if (e.key === 'Home') { LS.del('bellSize'); bellSize(p); bellPlace(p, $('#top .bell')); return; }
  const right = p.getBoundingClientRect().right, top = p.getBoundingClientRect().top;
  const w = Math.max(BELL_MIN.w * r, Math.min(p.offsetWidth + d[0], BELL_MAX_W * r, right - 12)), h = Math.max(BELL_MIN.h * r, Math.min(pop.offsetHeight + d[1], innerHeight - top - 12));
  p.style.width = w + 'px'; p.style.left = (right - w) + 'px'; pop.style.height = h + 'px'; pop.style.maxHeight = 'none';
  LS.set('bellSize', {w: Math.round(w / r * 100) / 100, h: Math.round(h / r * 100) / 100});
}
function bellPop(anchor) {
  if (!collab()) return;
  if (!$('#pop').classList.contains('hidden') && $('#pop .bpop')) { closePop(); return; }  // a second tap closes it
  const p = openPop(anchor, bellPopHtml(), () => {
    $('#top .bell')?.setAttribute('aria-expanded', 'false');
    p.onpointerdown = null; p.ondblclick = null; p.removeEventListener('keydown', bellGripKey); p.style.width = ''; p.classList.remove('bpfull', 'bellpop');
  });
  p.classList.add('bellpop');
  anchor?.setAttribute?.('aria-expanded', 'true');
  const redraw = () => { if ($('#pop .bpop') && !$('#pop').classList.contains('hidden')) { const y = $('#pop .bplist')?.scrollTop || 0; p.innerHTML = bellPopHtml(); bellSize(p); if (!isMobile()) bellPlace(p, anchor); const l = $('#pop .bplist'); if (l) l.scrollTop = y; } };  // 2.12.2 (#451): the list keeps its place
  bellSize(p); bellPlace(p, anchor); bellResizeWire(p, anchor);
  const fresh = S.nf.sig === (S.news?.sig ?? '') && S.nf.f === S.nf.filter && !!S.nf.items;
  if (!fresh) loadNews().then(redraw);
  setTimeout(() => $('#pop .bpop [data-bp="all"]')?.focus({preventScroll: true}), 30);
  p.onclick = async e => {
    const k = e.target.closest('[data-bpk]');
    if (k) { newsKindSet(k.dataset.bpk); redraw(); return; }
    const b = e.target.closest('[data-bp]'); if (!b) return;
    const i = +b.dataset.i, q = b.dataset.bp;
    if (q === 'dismiss') { e.stopPropagation(); await newsDismiss(i); redraw(); return; }
    // 2.13.0 (#453 A5): a task opened from the bell comes back to the bell (Back / closing the panel)
    if (q === 'open') { const it = (S.nf.items || [])[i]; closePop(); S.bellBack = !!it?.task_id && !['proposal', 'usage'].includes(it.kind) && (it.tasks || []).length < 2; newsOpen(i); return; }
    if (q === 'readall') { await newsReadAll(); redraw(); return; }
    if (q === 'settings') { closePop(); settingsModal('newskinds'); return; }
    if (q === 'all' || q === 'news') { closePop(); go('news'); }  // 2.7.0: the heading opens the News view too
  };
  p.onkeydown = e => { const it = e.target.closest?.('[data-bp="open"]'); if (it && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); it.click(); } };
}
// desktop: right-aligned under the bell (openPop places it at the anchor's left edge)
function bellPlace(p, anchor) {
  if (isMobile() || !anchor?.getBoundingClientRect) return;
  const r = anchor.getBoundingClientRect(), w = p.offsetWidth;
  if (!w) return;
  p.style.left = Math.max(12, Math.min(r.right - w, innerWidth - w - 12)) + 'px';
}
function relTime(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return tr('just now');
  if (min < 60) return trn('{0} min ago', '{0} min ago', min);
  if (min < 12 * 60) return trn('{0} h ago', '{0} h ago', Math.round(min / 60));
  return fmtWhen(iso);
}
// excerpt: one line, Markdown markers dropped, <@id> -> highlighted @name
const newsExcerpt = (body, U) => esc(String(body || '').replace(/\s+/g, ' ').replace(/\*\*|__|~~|`/g, '').replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1$2').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '$1').trim())
  .replace(/&lt;@(\d+)&gt;/g, (_, id) => `<span class="mention ${S.me && +id === S.me.id ? 'me' : ''}">@${esc(uname(+id, U))}</span>`);
// 1.10.0 list roles: [stored value, name, one-line explanation]; "edit" / "view" keep their stored values (API)
const ROLES = [['admin', N_('Admin'), N_('Sees and changes everything, manages the members')],
  ['edit', N_('Member'), N_('Sees and changes every task')],
  ['participant', N_('Participant'), N_('Sees only the tasks assigned to them')],
  ['view', N_('Viewer'), N_('Sees everything, changes nothing')]];
const roleLabel = r => r === 'owner' ? tr('Owner') : tr((ROLES.find(x => x[0] === r) || ROLES[1])[1]);
const roleHelp = r => r === 'owner' ? tr('Created the list; can rename, archive and delete it') : tr((ROLES.find(x => x[0] === r) || ROLES[1])[2]);
function newsListName(it) {
  const l = it.list_id && listById(it.list_id);
  return l ? (l.is_inbox ? tr('Inbox') : listName(l.name)) : listName(it.data?.name || '');
}
function newsText(it, U) {
  const d = it.data || {}, who = `<b>${esc(viaName(d, it.actor_id, U))}</b>`, q = x => `<b>${esc(x)}</b>`;
  switch (it.kind) {
    case 'mention': return tr('{0} mentioned you', who);
    case 'comment': if ((it.tasks || []).length > 1) return trn('{1} left {0} comments on {2} tasks', '{1} left {0} comments on {2} tasks', it.count, who, it.tasks.length);  // 2.13.0 (#453 A5)
      return it.count > 1 ? trn('{1} left {0} comments', '{1} left {0} comments', it.count, (it.actors || [it.actor_id]).map(a => `<b>${esc(uname(a, U))}</b>`).join(', ')) : tr('{0} commented', who);
    case 'assign': return d.group ? tr('{0} assigned a task to your group {1}', who, q(d.group)) : tr('{0} assigned a task to you', who);
    case 'take': return tr('{0} took a task of your group {1}', who, q(d.group || ''));  // 2.10.0 (#441)
    case 'unassign': return tr('{0} removed you as assignee', who);
    case 'complete': return tr('{0} completed a task', who);
    case 'share': return d.org ? (d.role === 'admin' ? tr('{0} added you to the organisation {1} as an admin', who, q(d.name || '')) : tr('{0} added you to the organisation {1}', who, q(d.name || '')))  // 2.28.0 (#935)
      : d.role === 'view' ? tr('{0} shared the list {1} with you (view only)', who, q(newsListName(it)))
      : d.role === 'participant' ? tr('{0} added you to {1} as a participant (you see the tasks assigned to you)', who, q(newsListName(it)))
        : d.role === 'admin' ? tr('{0} shared the list {1} with you as an admin', who, q(newsListName(it)))
          : d.group ? tr('{0} shared the list {1} with your group {2}', who, q(newsListName(it)), q(d.group)) : tr('{0} shared the list {1} with you', who, q(newsListName(it)));
    case 'role': return tr('{0} changed your role in {1} to {2}', who, q(newsListName(it)), q(roleLabel(d.role)));
    case 'unshare': return d.org ? tr('{0} removed you from the organisation {1}', who, q(d.name || '')) : tr('{0} removed you from the list {1}', who, q(newsListName(it)));  // 2.28.0 (#935)
    case 'owner': return tr('{0} made you the owner of the list {1}', who, q(newsListName(it)));  // 2.1.2 (#349)
    case 'unblock': return d.hidden ? tr('{0} completed a task you cannot see: your task is unblocked', who) : tr('{0} completed {1}: your task is unblocked', who, q(d.title || ''));
    case 'newtask': return tr('{0} added a task', who);
    case 'errreport': return d.title ? tr('New error reported: {0}', q(d.title)) : tr('A new error was reported');  // 2.18.0
    case 'approval': return tr('{0} is waiting for your approval', who);
    case 'apdecide': return {approved: tr('{0} approved {1}', who, q(it.task_title || '')), changes: tr('{0} asks for changes to {1}', who, q(it.task_title || '')),
      rejected: tr('{0} rejected {1}', who, q(it.task_title || ''))}[d.state] || tr('{0} decided on your approval request', who);  // 2.23.0 (#463)
    case 'signup': return tr('{0} registered and waits for your approval', q(d.name || d.username || ''));  // 2.23.0 (#711)
    case 'agentjoin': return d.provider ? tr('{0} added the agent {1} to {2}. It runs at {3}. What it reads in the list goes there.', who, q(d.agent || ''), q(newsListName(it)), q(d.provider))
      : tr('{0} added the agent {1} to {2}. What it reads in the list goes to its AI provider.', who, q(d.agent || ''), q(newsListName(it)));  // 2.24.0 (#896)
    case 'followup': return d.note ? tr('Follow up today: waiting on {0}', q(d.note)) : tr('Follow up today: the task is waiting on someone');
    case 'usage': return aiuNewsText(d);  // 2.1.1 (#326)
    case 'proposal': return tr('{0} has a proposal for you: {1}', who, q(d.title || ''));  // 2.3.0
    case 'evinvite': case 'evshare': return evNewsText(it, who, q);  // 2.21.0 (#659)
    case 'abshare': return d.role === 'edit' ? tr('{0} shared the address book {1} with you', who, q(d.name || '')) : tr('{0} shared the address book {1} with you (view only)', who, q(d.name || ''));  // 2.21.0 (#658)
    case 'status': return d.status ? tr('{0} set {1} to {2}', who, q(newsListName(it)), `<span class="stpill st-${esc(d.status)} inl"><i></i>${esc(statusLabel(d.status))}</span>`) : tr('{0} cleared the status of {1}', who, q(newsListName(it)));
  }
  return tr('{0} changed something', who);
}
const NEWS_ICON = {mention: 'at', comment: 'comment', assign: 'user', unassign: 'user', take: 'check', complete: 'check', share: 'users', role: 'users', unshare: 'users', unblock: 'deps', status: 'pulse', newtask: 'plus', approval: 'bot', followup: 'hourglass', usage: 'chart', proposal: 'bot', errreport: 'bug', apdecide: 'eye', signup: 'user', agentjoin: 'bot'};
function newsItemHtml(it, i, pop) {
  const U = S.nf.users;
  const many = (it.tasks || []).length > 1;  // 2.13.0 (#453 A5): an agent's comments on several tasks
  const task = many ? `<div class="ntask"><span class="nt">${esc(it.tasks.slice(0, 2).map(x => x.title).join(' · '))}</span>${it.tasks.length > 2 ? `<span class="muted">+${it.tasks.length - 2}</span>` : ''}</div>`
    : it.task_id ? `<div class="ntask"><span class="nt">${esc(it.task_title || '')}</span><span class="muted nl">${esc(newsListName(it))}</span></div>` : '';
  const ex = it.excerpt ? `<div class="nexc">${newsExcerpt(it.excerpt, U)}</div>` : '';
  return `<div class="nitem ${it.read ? '' : 'unread'} k-${esc(it.kind)} ${it.to_me ? 'tome' : ''}" role="button" tabindex="0" ${pop ? 'data-bp="open"' : 'data-act="news-open"'} data-i="${i}" aria-label="${esc((it.read ? '' : tr('Unread') + ': ') + newsText(it, U).replace(/<[^>]+>/g, ''))}">
    ${it.actor_id ? `<button type="button" class="avb" data-mcard="${+it.actor_id}" data-mname="${esc(uname(it.actor_id, U))}" aria-haspopup="dialog" title="${esc(tr('Show {0}', uname(it.actor_id, U)))}" aria-label="${esc(tr('Show {0}', uname(it.actor_id, U)))}">` : ''}${av(it.actor_id, uname(it.actor_id, U), 'avatar', '', `<i class="nk">${ic(NEWS_ICON[it.kind] || 'bell', 's')}</i>`)}${it.actor_id ? '</button>' : ''}
    <div class="nmain"><div class="ntext">${newsText(it, U)}</div>${task}${ex}</div>
    <time title="${esc(fmtWhen(it.created_at))}">${relTime(it.created_at)}</time>${isTouch() ? '' : `<button class="iconbtn ndel" ${pop ? 'data-bp="dismiss"' : 'data-act="news-dismiss"'} data-i="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>`}</div>`;
}
// 2.25.0 (UX-47): what lands in News (the bell) and what does not
const newsWhat = () => teamOn() ? tr('Assignments, @mentions, comments on your tasks and follow-ups land here. Messages are in the team chat.') : tr('Assignments, @mentions, comments on your tasks and follow-ups land here.');
const newsTab = () => { const t = LS.get('newsTab', 'all'); return ['me', 'act', 'all'].includes(t) ? t : 'all'; };  // 2.28.0 (#987): all = both sections, For you first
function viewNews() {
  const f = S.nf.filter, fresh = S.nf.sig === (S.news?.sig ?? '') && S.nf.f === f && !!S.nf.items;
  // 1.9.0 (#246): "Loading…" only while a request really runs; an empty feed says so instead of loading forever
  if (!fresh && !S.nf.loading && !S.nf.queued) { S.nf.queued = true; setTimeout(() => { S.nf.queued = false; loadNews(); }, 0); }
  // 2.13.0 (#453 P9): ONE filter row: "All" (clears both), "Mentions & assigned to me" (server filter) and the kinds
  const k0 = S.nf.kind, fchips = (items) => { const h = newsChipsHtml(items || [], 'data-nk').replace(/^<div class="nchips"[^>]*>/, '').replace(/<\/div>$/, '').replace(/<button type="button" class="nchip [^"]*" data-act="news-kind" data-nk="" aria-pressed="[^"]*">[^<]*<\/button>/, '');
    return `<div class="nchips nfrow" role="group" aria-label="${esc(tr('Show only'))}"><button type="button" class="nchip ${f || k0 ? '' : 'on'}" data-act="news-filter" data-f="" data-nk="" aria-pressed="${!f && !k0}">${tr('All')}</button><button type="button" class="nchip ${f ? 'on' : ''}" data-act="news-filter" data-f="me" data-fme aria-pressed="${!!f}">${ic('at', 's')}${tr('Mentions & assigned to me')}</button>${h}</div>`; };
  const bar0 = `<div class="nbar"><button class="btn sm ntog ${S.nf.unread ? 'on' : ''}" data-act="news-unread" aria-pressed="${S.nf.unread}" title="${esc(tr('Hide news you have already read'))}">${ic('eye', 's')}${tr('Unread only')}</button><button class="btn sm ntog ${newsBundled() ? 'on' : ''}" data-act="news-bundle" aria-pressed="${newsBundled()}" title="${esc(tr('Group by task, what needs you first'))}">${ic('columns', 's')}${tr('Bundled')}</button><span class="spacer"></span>${S.news?.unread && (S.agents || []).some(x => x.enabled) ? `<button class="btn sm" data-act="news-sum" aria-haspopup="menu" title="${esc(tr('An agent summarizes your unread news in its chat'))}">${ic('bot', 's')}${tr('Summarize')}</button>` : ''}${S.news?.unread ? `<button class="btn sm" data-act="news-readall">${ic('check', 's')}${tr('Mark all as read')}</button>` : ''}<button class="iconbtn" data-act="news-settings" title="${esc(tr('What shows up here'))}" aria-label="${esc(tr('What shows up here'))}">${ic('gear', 's')}</button></div>`;
  const mine0 = S.nf.items && S.nf.f === f ? S.nf.items : null;
  // 2.28.0 (#987): "For you" (people: mentions, assignments, replies, direct messages) | "Activity" (changes, agents) | All
  const tab = newsTab(), nMe = (mine0 || []).filter(it => !it.read && newsForMe(it) && newsInWs(it)).length + dmRows().reduce((a, r) => a + r.unread, 0), nAct = (mine0 || []).filter(it => !it.read && !newsForMe(it) && newsInWs(it)).length;
  if (teamOn() && S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.route.mod === 'news') renderView(); }); }
  const tabs = `<div class="seg ntabs" role="tablist" aria-label="${esc(tr('News'))}">${[['all', 'bell', N_('All'), 0], ['me', 'at', N_('For you'), nMe], ['act', 'pulse', N_('Activity'), nAct]].map(([k, i, n, c]) => `<button type="button" role="tab" class="${tab === k ? 'on' : ''}" aria-selected="${tab === k}" data-act="news-tab" data-tab="${k}">${ic(i, 's')}<span>${tr(n)}</span>${c ? `<span class="c nunread">${c}</span>` : ''}</button>`).join('')}</div>`;
  const inTab = it => newsInWs(it) && (tab === 'all' || (tab === 'me') === newsForMe(it));
  const bar = tabs + bar0 + fchips((mine0 || []).filter(it => (!S.nf.unread || !it.read || it.keep) && inTab(it)));
  if (S.nf.err && !S.nf.items) return bar + `<div class="empty">${S.nf.err === 'offline' ? tr('News are only available online.') : esc(S.nf.err)}</div>`;
  const mine = S.nf.items && S.nf.f === f ? S.nf.items : null;
  if (!mine && (S.nf.loading || S.nf.queued)) return bar + `<div class="empty">${tr('Loading…')}</div>`;
  // #302 unread only: read items hide (one opened just now stays until the next load); data-i keeps the index in S.nf.items
  const vis = (mine || []).map((it, i) => [it, i]).filter(([it]) => (!S.nf.unread || !it.read || it.keep) && inTab(it));
  const dms = tab === 'act' ? [] : dmRows().filter(r => !S.nf.unread || r.unread);
  const dmh = dms.length ? `<div class="nlist ndms">${dms.map(dmRowHtml).join('')}</div>` : '';
  const chips = '';  // 2.13.0: in the one filter row of the bar
  const shown = vis.filter(([it]) => newsKindOk(it));
  if (mine && mine.length && !vis.length && !dms.length) return bar + `<div class="empty nempty">${ic('bell')}<b>${tab === 'me' ? tr('Nothing for you right now') : tr('No unread news')}</b><span>${tab === 'me' ? tr('Mentions, assignments, replies and direct messages from people land here.') : tr('Everything is read. Switch off “Unread only” to see older news.')}</span></div>`;
  if ((!mine || !mine.length) && !dms.length) return bar + `<div class="empty nempty">${ic('bell')}<b>${tr('No news')}</b><span>${f ? tr('No mentions or assignments.') : esc(newsWhat())}</span></div>`;
  if (!shown.length && !dms.length) return bar + chips + `<div class="empty nempty">${ic('bell')}<b>${tr('Nothing of this kind.')}</b></div>`;
  // 2.28.0 (#987): "All" shows the two sections, what people sent me first, the activity behind it
  const listHtml = () => { if (newsBundled()) return `<div class="nbund">${newsBundledHtml(shown, false)}</div>`; if (tab !== 'all') return `<div class="nlist">${shown.map(([it, i]) => newsItemHtml(it, i)).join('')}</div>`;
    const me_ = shown.filter(([it]) => newsForMe(it)), ac = shown.filter(([it]) => !newsForMe(it));
    return `<div class="nlist">${dms.length || me_.length ? newsSecHead('me', dms.reduce((a, r) => a + r.unread, 0) + me_.filter(([it]) => !it.read).length, true) + dmh + me_.map(([it, i]) => newsItemHtml(it, i)).join('') : ''}${ac.length ? newsSecHead('act', ac.filter(([it]) => !it.read).length, !dms.length && !me_.length) + ac.map(([it, i]) => newsItemHtml(it, i)).join('') : ''}</div>`; };
  return bar + chips + (tab === 'all' && !newsBundled() ? '' : dmh) + listHtml() + `${isTouch() && !newsBundled() ? `<div class="muted nswipe">${tr('Swipe an item sideways to remove it.')}</div>` : ''}`;
}
async function loadNews() {
  if (S.nf.loading) return;
  const f = S.nf.filter;
  if (!collab()) { Object.assign(S.nf, {items: [], f, sig: S.news?.sig ?? '', err: null}); if (S.route.mod === 'news') renderView(); return; }
  S.nf.loading = true;
  try {
    const j = await rawFetch('GET', '/api/news' + (f ? '?filter=' + f : ''));
    Object.assign(S.nf, {items: j.items, users: j.users || {}, sig: j.sig, f, err: null});
    if (j.avatars) S.avatars = {...(S.avatars || {}), ...j.avatars};
    const changed = !S.news || S.news.unread !== j.unread || S.news.sig !== j.sig || S.news.unread_me !== j.unread_me;
    S.news = {unread: j.unread, unread_me: j.unread_me ?? S.news?.unread_me ?? 0, sig: j.sig};
    if (changed) { renderTop(); renderTabs(); renderSide(); }
  } catch (e) {
    if (e.message !== 'auth') { S.nf.err = e instanceof Offline ? 'offline' : e.message; S.nf.sig = S.news?.sig ?? ''; S.nf.f = f; }
  } finally { S.nf.loading = false; }
  if (S.route.mod === 'news') renderView();
}
// 2.13.0 (#453 A5): "Mark all as read" says how many and can be undone (the server returns the ids it marked)
async function newsReadAll() {
  const before = (S.nf.items || []).filter(x => !x.read), n = S.news?.unread || before.length;
  before.forEach(x => { x.read = true; });
  const j = await newsRead({all: true});
  const ids = j?.marked || before.flatMap(x => x.ids || []);
  if (!ids.length) return;
  toast(trn('{0} marked as read', '{0} marked as read', n), async () => {
    before.forEach(x => { x.read = false; x.keep = true; });
    try { const k = await rawFetch('POST', '/api/news/read', {unread: true, ids}); S.news = {unread: k.unread, unread_me: k.unread_me ?? S.news?.unread_me ?? 0, sig: k.sig}; S.nf.sig = null; } catch { toast(tr('Only available online.')); }
    render(); if ($('#pop .bpop')) { const b = $('#top .bell'); closePop(); if (b) bellPop(b); }
  });
}
async function newsRead(body) {
  wpCloseLocal(body.all ? (S.nf.items || []).map(x => x.task_id) : (S.nf.items || []).filter(x => (x.ids || []).some(i => (body.ids || []).includes(i))).map(x => x.task_id));
  if (body.all) wpSweep(null, true);  // 2.19.0 (#668): "Mark all as read" closes every notification (here; the server the others)
  try {
    const j = await rawFetch('POST', '/api/news/read', body);
    S.news = {unread: j.unread, unread_me: j.unread_me ?? S.news?.unread_me ?? 0, sig: j.sig}; S.nf.sig = j.sig;
    render(); return j;
  } catch { /* offline: stays unread on the server */ }
  render();
}
// 1.9.0: remove single items (x on desktop, swipe on touch) like mails from an inbox; one undo-less step (they are only
// notices; the task itself is untouched)
async function newsDismiss(i) {
  const it = (S.nf.items || [])[i]; if (!it) return;
  S.nf.items.splice(i, 1);
  if (!it.read && S.news) { S.news.unread = Math.max(0, (S.news.unread || 0) - 1); if (it.to_me) S.news.unread_me = Math.max(0, (S.news.unread_me || 0) - 1); }
  renderView(); renderTop(); renderTabs(); renderSide();
  try {
    const j = await rawFetch('POST', '/api/news/dismiss', {ids: it.ids});
    S.news = {unread: j.unread, unread_me: j.unread_me ?? S.news?.unread_me ?? 0, sig: j.sig}; S.nf.sig = j.sig;
  } catch { S.nf.sig = null; }  // offline: reloaded next time
  render();
}
(() => {  // swipe an item sideways (touch)
  let s = null;
  document.addEventListener('touchstart', e => { const n = e.target.closest?.('.nitem'); s = n && e.touches.length === 1 ? {n, x: e.touches[0].clientX, y: e.touches[0].clientY, dx: 0, h: false} : null; }, {passive: true});
  document.addEventListener('touchmove', e => {
    if (!s) return;
    const dx = e.touches[0].clientX - s.x, dy = e.touches[0].clientY - s.y;
    if (!s.h && Math.abs(dy) > Math.abs(dx)) { s = null; return; }
    if (Math.abs(dx) > 8) s.h = true;
    if (!s.h) return;
    s.dx = dx; s.n.style.transition = 'none'; s.n.style.transform = `translateX(${dx}px)`; s.n.style.opacity = String(Math.max(.25, 1 - Math.abs(dx) / 260));
  }, {passive: true});
  document.addEventListener('touchend', () => {
    if (!s) return; const {n, dx, h} = s; s = null; if (!h) return;
    n.style.transition = 'transform .18s ease, opacity .18s ease';
    if (Math.abs(dx) > Math.min(120, n.offsetWidth * .35)) {
      n.style.transform = `translateX(${dx > 0 ? '' : '-'}110%)`; n.style.opacity = '0'; n.dataset.swiped = '1';
      setTimeout(() => newsDismiss(+n.dataset.i), 170);
    } else { n.style.transform = ''; n.style.opacity = ''; }
  }, {passive: true});
  document.addEventListener('click', e => { const n = e.target.closest?.('.nitem[data-swiped]'); if (n) { e.stopPropagation(); e.preventDefault(); } }, true);
})();
async function newsOpen(i) {
  const it = (S.nf.items || [])[i]; if (!it) return;
  if (!it.read) { it.read = true; it.keep = true; if (it.to_me && S.news) { S.news.unread_me = Math.max(0, (S.news.unread_me || 0) - 1); renderTop(); } newsRead({ids: it.ids}); }
  if (/comment|mention/.test(it.kind || '')) S.tlScroll = it.task_id;  // 2.0.6: opened for a comment: show the newest
  if (it.kind === 'proposal') { propOpen(it.data?.job); return; }  // 2.3.0
  if (it.kind === 'evinvite' && it.data?.event_id) { evOpen(it.data.event_id); return; }  // 2.21.0 (#659 / #658)
  if (it.kind === 'evshare') { go('cal'); setTimeout(evCalsModal, 150); return; }
  if (it.kind === 'abshare') { go('contacts'); return; }
  if (it.kind === 'usage') { if (feat('agents') && agentsOn()) go('agents'); else settingsModal('usage'); return; }  // 2.1.1 (#326)
  if (it.kind === 'approval' && !it.task_id && feat('agents') && agentsOn()) { go('agents'); return; }
  if (it.kind === 'signup') { settingsModal('users'); return; }  // 2.23.0 (#711): approve it under Users  // 2.15.0 (#479): an agent's request
  if (!it.task_id) { if (it.list_id && listById(it.list_id)) go('l/' + it.list_id); return; }
  if (!taskById(it.task_id)) {  // e.g. completed long ago: not in the state
    try { (S.extra ||= []).push(await rawFetch('GET', `/api/tasks/${it.task_id}`)); }
    catch (e) { toast(e instanceof Offline ? tr('News are only available online.') : tr('Task not found')); return; }
  }
  openDetail(it.task_id);
}

// ------------------------------------------------------------------ comments + activity (module "collab")
// Loaded per task when the detail panel opens (GET /timeline), refreshed when the version changes.
// Comments are sent directly (never queued offline): offline, the text stays in the box with a notice.
const showAct = () => LS.get('showActivity', true);
// 2.4.2 (#386): comment order per user (all devices): old = oldest first, the box at the bottom edge (sticky);
// new = newest first, the box right above the newest comment (no scrolling to answer)
const cmtNew = () => S.settings?.comment_order === 'new';
// 2.31.0 (#1054): the "…" of the comment head: order (saved per user) and the history between the comments (per device)
function tlMenu(anchor) {
  const t = taskById(S.sel); if (!t) return;
  const nw = cmtNew(), keep = tr('Order of the comments, saved for you on all devices');
  menu(anchor, [{label: tr('Oldest first'), icon: 'sort', on: !nw, cls: 'mtlold', title: keep, fn: () => { if (nw) cmtOrderToggle(); }},
    {label: tr('Newest first'), icon: 'sort', on: nw, cls: 'mtlnew', title: keep, fn: () => { if (!nw) cmtOrderToggle(); }},
    ...(cmSocial(t) ? ['-', {label: tr('With activity'), icon: 'clock', on: showAct(), cls: 'mtlact', title: tr('Show the history of changes between the comments'), fn: tlActToggle}] : [])]);
}
function tlActToggle() { LS.set('showActivity', !showAct()); renderDetail(); }
async function cmtOrderToggle() {
  const v = cmtNew() ? 'old' : 'new', f = document.activeElement?.id === 'c-input';
  S.settings.comment_order = v; renderDetail(); if (f) $('#c-input')?.focus();
  try { await api('PATCH', '/api/settings', {comment_order: v}); } catch { /* api() showed it; the local choice stays until the next load */ }
}
const uname = (id, U) => (U || {})[id] || (id ? tr('Deleted user') : tr('Someone'));
function fmtWhen(iso) {
  const d = new Date(iso), hmTxt = d.toLocaleTimeString(LOCALE(), {hour: '2-digit', minute: '2-digit'});
  if (ds(d) === today()) return hmTxt;
  if (ds(d) === addDays(today(), -1)) return tr('Yesterday') + ' ' + hmTxt;
  return fmtDay(d.getFullYear() !== new Date().getFullYear() ? 'year' : 'short', d) + ' ' + hmTxt;
}
const fmtDayAbs = s => fmtDay(pd(s).getFullYear() !== new Date().getFullYear() ? 'year' : 'short', pd(s));
function actText(a, U) {  // "via API" after lines written through a personal access token
  return actText0(a, U) + (a.data?.via === 'api' ? ` <span class="via">${tr('via API')}</span>` : a.data?.via === 'caldav' ? ` <span class="via">${tr('via CalDAV')}</span>` : '');
}
const viaName = (d, id, U) => d?.via === 'public_link' && !id ? tr('Someone via the public link') : uname(id, U);
function actText0(a, U) {
  const d = a.data || {}, who = `<b>${esc(viaName(d, a.user_id, U))}</b>`, q = x => `<b>${esc(x)}</b>`;
  const due = () => q((d.start && d.start < d.due ? fmtDayAbs(d.start) + ' – ' : '') + fmtDayAbs(d.due) + (d.time ? ', ' + d.time : ''));
  switch (a.kind) {
    case 'created': if (d.report) return tr('Created from an error report ({0})', q(d.report === 'sentry' ? 'Sentry' : tr('webhook')));  // 2.18.0 (#408)
      return d.proposal ? tr('{0} created the task from a proposal by {1}', who, q(uname(d.agent, U))) : tr('{0} created the task', who);
    case 'proposal': return tr('{0} applied a proposal by {1}', who, q(uname(d.agent, U)));  // 2.3.0 (#262)
    case 'event': return tr('The task became an event; the people who came along are invited to it');  // 2.21.0 (#659)
    case 'title': return tr('{0} renamed the task to “{1}”', who, esc(d.to || ''));
    case 'content': return tr('{0} edited the description', who);
    case 'due': return d.due ? tr('{0} set the due date to {1}', who, due()) : tr('{0} removed the due date', who);
    case 'snooze': return tr('{0} snoozed the task to {1}', who, due());
    case 'dep_shift': return tr('{0} moved a task that blocks this one, so it moved along to {1}', who, due());
    case 'priority': return tr('{0} changed the priority to {1}', who, q(tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High')][+d.p] || N_('None'))));
    case 'assign': return d.to ? tr('{0} assigned the task to {1}', who, q(uname(d.to, U))) : tr('{0} removed the assignee', who);
    case 'assign_group': return d.group ? tr('{0} assigned the task to the group {1}', who, q(d.group)) : tr('{0} removed the group', who);  // 2.10.0 (#441)
    case 'take': return tr('{0} took the task (group {1})', who, q(d.group || ''));
    case 'list': return tr('{0} moved the task to the list {1}', who, q(d.inbox && inboxDef(d.name) ? tr('Inbox') : listName(d.name)));
    case 'section': return d.name ? tr('{0} moved the task to the section {1}', who, q(d.name)) : tr('{0} removed the task from its section', who);
    case 'parent': return d.title ? tr('{0} made the task a subtask of {1}', who, q(d.title)) : tr('{0} made the task a main task', who);
    case 'ttype': return d.to ? tr('{0} set the type to {1}', who, q(ttName(d.to))) : tr('{0} removed the type', who);  // 2.4.0 (#340)
    case 'ms': return d.on ? tr('{0} made the task a milestone', who) : tr('{0} made the milestone a normal task', who);  // 2.18.0 (#430)
    case 'milestone': return d.title ? tr('{0} added the task to the milestone {1}', who, q(d.title)) : tr('{0} removed the task from its milestone', who);
    case 'repeat': return d.rule ? tr('{0} set the repetition to {1}', who, q(repeatLabel(d.rule))) : tr('{0} stopped the repetition', who);
    case 'link': return d.url ? tr('{0} set the link to {1}', who, q(urlHost(d.url))) : tr('{0} removed the link', who);
    case 'complete': return d.next ? tr('{0} completed the task, next occurrence {1}', who, q(fmtDayAbs(d.next))) : tr('{0} completed the task', who);
    case 'wont': return tr("{0} marked the task as won't do", who);
    case 'reopen': return tr('{0} reopened the task', who);
    case 'skip': return tr('{0} skipped an occurrence, next one {1}', who, q(fmtDayAbs(d.next)));
    case 'attach': return (d.n || 1) === 1 ? tr('{0} added the attachment {1}', who, q((d.names || [])[0] || '')) : trn('{1} added {0} attachment', '{1} added {0} attachments', d.n, who);
    case 'attach_rm': return tr('{0} removed the attachment {1}', who, q(d.name || ''));
    case 'paperless': return tr('{0} linked the Paperless document {1}', who, q(d.title || ''));
    case 'waiting': return d.until ? tr('{0} set the task to waiting on someone ({1}), follow up on {2}', who, q(d.note || '–'), q(dayLabel(d.until))) : tr('{0} set the task to waiting on someone ({1})', who, q(d.note || '–'));
    case 'waiting_rm': return tr('{0} ended the waiting on someone', who);
    case 'paperless_rm': return tr('{0} removed the Paperless document {1}', who, q(d.title || ''));
    case 'paperless_send': return tr('{0} sent {1} to Paperless', who, q(d.name || ''));
    case 'subtask': return tr('{0} added the subtask {1}', who, q(d.title || ''));
    case 'dep_add': return d.hidden ? tr('{0} marked the task as blocked by a task you cannot see', who) : tr('{0} marked the task as blocked by {1}', who, q(d.title || ''));
    case 'dep_rm': return d.hidden ? tr('{0} removed a dependency on a task you cannot see', who) : tr('{0} removed the dependency on {1}', who, q(d.title || ''));
    case 'blocks_add': return d.hidden ? tr('{0} marked the task as blocking a task you cannot see', who) : tr('{0} marked the task as blocking {1}', who, q(d.title || ''));
    case 'blocks_rm': return d.hidden ? tr('{0} removed the task as a blocker of a task you cannot see', who) : tr('{0} removed the task as a blocker of {1}', who, q(d.title || ''));
    case 'unblocked': return d.hidden ? tr('{0} completed the last task blocking this one', who) : tr('{0} completed {1}, the task is no longer blocked', who, q(d.title || ''));
    case 'field': return d.v == null ? tr('{0} cleared the field {1}', who, q(d.name || '')) : tr('{0} set {1} to {2}', who, q(d.name || ''), q(actField(d)));
    case 'apstate': return {pending: tr('{0} asked {1} for approval', who, q(uname(d.approver, U))), approved: tr('{0} approved the task', who), changes: tr('{0} asked for changes', who),
      rejected: tr('{0} rejected the task', who), cancelled: tr('{0} withdrew the approval request', who)}[d.state] + (d.note ? ': ' + q(d.note) : '');  // 2.23.0 (#463)
    case 'approval': return d.ok ? tr('{0} approved the comment of {1}', who, q(uname(d.agent, U))) : tr('{0} rejected the comment of {1}', who, q(uname(d.agent, U)));
    case 'agent_job': return d.action === 'approve' ? tr('{0} approved the job {2} of {1}', who, q(uname(d.agent, U)), q(d.title || ''))
      : d.action === 'reject' ? tr('{0} rejected the job {2} of {1}', who, q(uname(d.agent, U)), q(d.title || '')) : tr('{0} stopped the job {2} of {1}', who, q(uname(d.agent, U)), q(d.title || ''));
    case 'tidy': return tr('{0} tidied up the task (the original text is at the top of the notes)', who);
    case 'ltags': return d.tags?.length ? tr('{0} set the list tags {1}', who, q(d.tags.map(g => '#' + g).join(' '))) : tr('{0} removed the list tags', who);
    case 'delete': return tr('{0} moved the task to the trash', who);
    case 'restore': return tr('{0} restored the task', who);
    case 'import': return tr('{0} imported the task from {1}', who, q(d.source || ''));
    case 'git_pr': case 'git_done': return gitActText(a, d, q);  // 2.2.0 (#271)
    case 'err_again': return tr('The error happened again ({0}×)', d.n || 2) + (d.level ? ` <span class="muted">· ${esc(d.level)}</span>` : '');  // 2.18.0 (#408)
  }
  return tr('{0} changed the task', who);
}
// comment text: the same markdown as a description (renderMd: headings, lists, read-only checkboxes, bold, code, links;
// 2.13.2 #478 N4, before only inline), <@id> -> highlighted @name; compact in comments and chat bubbles (.mdc)
function commentBody(body, U, lid) {  // 2.18.0 (#408 G): lid = the list (file:line links into its repository)
  return `<div class="md mdc">${renderMd(body, true, {lid})}</div>`
    .replace(/&lt;@(\d+)&gt;/g, (_, id) => mentionTag(+id, uname(+id, U), !!(U || {})[id] || !!agentById(id)));
}
// 2.4.2 (#389): a mention is a button that opens a small card about the person or agent; a name nobody has stays text
const mentionTag = (id, name, known = true) => known
  ? `<button type="button" class="mention mlink ${S.me && id === S.me.id ? 'me' : ''}" data-mcard="${id}" aria-haspopup="dialog" title="${esc(tr('Show {0}', name))}">@${esc(name)}</button>`
  : `<span class="mention">@${esc(name)}</span>`;
// descriptions store plain "@Name" (or "@username"): only names of people / agents of the task's list become buttons
function mdMentions(html, t) {
  const l = t && listById(t.list_id); if (!l || !collab() || !html.includes('@')) return html;
  const names = [];
  for (const p of listPeople(l)) {
    if (p.name) names.push([p.name, p.user_id]);
    if (p.username && p.username !== p.name) names.push([p.username, p.user_id]);
  }
  if (!names.length) return html;
  names.sort((a, b) => b[0].length - a[0].length);
  const alt = names.map(([n]) => esc(n).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const re = new RegExp(`(^|[^\\p{L}\\p{N}_@/])@(${alt})(?![\\p{L}\\p{N}_])`, 'giu');
  // only text between tags, never inside <code> / <a> (links and code keep their text)
  let skip = 0;
  return html.split(/(<[^>]+>)/).map(part => {
    if (part.startsWith('<')) { if (/^<(code|a)[\s>]/i.test(part)) skip++; else if (/^<\/(code|a)>/i.test(part)) skip = Math.max(0, skip - 1); return part; }
    if (skip) return part;
    return part.replace(re, (m, pre, n) => { const hit = names.find(([x]) => esc(x).toLowerCase() === n.toLowerCase()); return hit ? pre + mentionTag(hit[1], n.startsWith(esc(hit[0])) ? hit[0] : n) : m; });
  }).join('');
}
function mentionCard(anchor) { personCard(anchor, +anchor.dataset.mcard); }
// 2.5.1 / 2.7.2 (#418): the card of a person or an agent. Inside the task panel with the task's list as context (role,
// tasks assigned in that list, Assign, Mention); elsewhere without a list. Only what the viewer may see: names come from
// lists they share, tasks from their own state.
function personCard(anchor, id) {
  const inTask = !!anchor.closest?.('#detail, .dsheet, .dpanel') && !!S.sel;
  const t = inTask ? taskById(S.sel) : null, l = t ? listById(t.list_id) : null;
  const p = listPeople(l).find(x => x.user_id === id), a = agentById(id);
  const name = p?.name || a?.name || anchor.dataset.mname || personNameAny(id) || anchor.textContent.replace(/^@/, ''), meId = S.me?.id;
  const role = p ? roleLabel(p.role) : '', U = S.tl.users || {};
  const st = a ? `<span class="mcst st-${esc(!a.enabled ? 'paused' : agentOffline(a) ? 'offline' : a.status || 'idle')}">${esc(agentSt(a))}${a.status_text ? ' · ' + esc(a.status_text) : ''}</span>` : '';
  const mine = l ? openTasks().filter(x => x.list_id === l.id && x.assignee_id === id && x.id !== t?.id).sort(bySort) : [];
  const acts = [];
  if (a && a.enabled && typeof chatOpen === 'function') acts.push(['chat', 'comment', tr('Open chat')]);
  if (a && feat('agents')) acts.push(['jobs', 'bot', tr('Jobs')]);
  if (!a && id !== meId) acts.push(['dm', 'comment', tr('Message')]);  // 2.24.0 (#906): a direct message, first and big
  if (!a) acts.push(['who', 'list', id === meId ? tr('My tasks') : tr('Tasks of {0}', name)]);  // 2.7.2 (#418)
  if (t && !t.context && id !== t.assignee_id && canAssign(t) && p) acts.push(['assign', 'user', tr('Assign this task')]);
  if (t && $('#c-input') && cmSocial(t) && id !== meId && p) acts.push(['mention', 'at', tr('Mention')]);
  // 2.7.2 (#418): what an agent works on right now (only a task the viewer sees)
  const cur = a ? [a.status_task, ...(a.job_tasks || [])].filter(Boolean).filter((x, i, arr) => arr.indexOf(x) === i).slice(0, 3) : [];
  const curHtml = a ? `<div class="mcsec"><div class="mch">${esc(tr('Working on'))}</div>${cur.map(x => { const tk = taskById(x); return `<button type="button" class="mctask" data-mc="task" data-id="${x}">${ic('sub', 's')}<span>${esc(tk ? tk.title : tr('Task {0}', '#' + x))}</span></button>`; }).join('') || `<div class="muted mhint">${esc(tr('No task right now'))}</div>`}</div>` : '';
  const pop = openPop(anchor, `<div class="mcard" role="dialog" aria-label="${esc(name)}"><div class="mchead">${av(id, name, 'avatar lg')}<div class="mcn"><b>${esc(name)}${id === meId ? ' ' + esc(tr('(me)')) : ''}</b>${a ? agentBadge() : ''}
      <span class="muted">${esc(role || (U[id] ? '' : tr('Not a member of this list')))}</span>${st}</div></div>
    ${l && p ? `<div class="mcsec"><div class="mch">${esc(tr('Assigned in {0}', lname(l)))} <span class="c">${mine.length}</span></div>${mine.slice(0, 5).map(x => `<button type="button" class="mctask" data-mc="task" data-id="${x.id}">${ic('check', 's')}<span>${esc(x.title)}</span></button>`).join('') || `<div class="muted mhint">${esc(tr('No other open tasks'))}</div>`}${mine.length > 5 ? `<div class="muted mhint">${esc(trn('and {0} more', 'and {0} more', mine.length - 5))}</div>` : ''}</div>` : ''}
    ${curHtml}
    ${acts.length ? `<div class="mcacts">${acts.map(([k, i, lab]) => `<button type="button" class="btn sm ${k === 'dm' ? 'pri mcdm' : ''}" data-mc="${k}">${ic(i, 's')} ${esc(lab)}</button>`).join('')}</div>` : ''}</div>`);
  pop.onclick = async e => {
    const b = e.target.closest('[data-mc]'); if (!b) return;
    const k = b.dataset.mc; closePop();
    if (k === 'task') { const x = +b.dataset.id; if (S.tasks.get(x)) openDetail(x); else go('t/' + x); }
    else if (k === 'who') { if (S.sel && isMobile()) closeDetail(); go('who/' + id); }
    else if (k === 'dm') { if (S.sel && isMobile()) closeDetail(); dmOpen(id, name); }
    else if (k === 'chat') chatOpen(id);
    else if (k === 'jobs') go('agents');
    else if (k === 'assign') patchTask(t.id, {assignee_id: id});
    else if (k === 'mention') { const ta = $('#c-input'); if (!ta) return; const add = (ta.value && !/\s$/.test(ta.value) ? ' ' : '') + '@' + name + ' '; ta.value += add; S.drafts[S.sel] = ta.value; ta.closest('.ccomp')?.classList.add('used'); autosize(ta); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
  };
}
document.addEventListener('click', e => {  // 2.7.2 (#418): before the row / list / dialog handlers under the picture
  const b = e.target.closest?.('.avb[data-mcard]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); personCard(b, +b.dataset.mcard);
}, true);
const decodeMentions = (body, U) => String(body || '').replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, U));
function encodeMentions(text, people) {
  for (const p of [...(people || [])].sort((a, b) => b.name.length - a.name.length))
    text = text.replace(new RegExp('@' + p.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\p{L}\\p{N}_])', 'gu'), `<@${p.id}>`);
  return text;
}
function cattHtml(a, cid, editing) {
  const del = editing ? `<button class="attdel" data-act="catt-del" data-att="${a.id}" title="${tr('Remove')}">${ic('x', 's')}</button>` : '';
  if (isImg(a)) return `<div class="att img"><a href="${attUrl(a)}" data-act="catt-view" data-att="${a.id}" data-cid="${cid}" title="${esc(a.name)}"><img src="${attUrl(a)}" loading="lazy" alt="${esc(a.name)}"></a>${del}</div>`;
  return `<div class="att file">${attFileA(a)}${del}</div>`;  // 2.30.0 (#1035): text files open in the viewer
}
function commentHtml(c, U, ro = false) {
  const mine = S.me && c.user_id === S.me.id, editing = !ro && S.cedit === c.id;
  const isNew = !ro && !mine && c.id > (S.tl.seen || 0);
  // 2.33.0 (#1076): Reply on every comment (hover / keyboard; phones swipe right)
  const acts = ro ? '' : `<span class="cacts">${editing ? '' : replyBtn()}${mine ? `<button class="iconbtn" data-act="c-edit" data-cid="${c.id}" title="${tr('Edit')}">${ic('edit', 's')}</button>` : ''}${mine || S.tl.moderator ? `<button class="iconbtn" data-act="c-del" data-cid="${c.id}" title="${tr('Delete')}">${ic('trash', 's')}</button>` : ''}</span>`;
  const files = c.attachments?.length ? `<div class="atts catts">${c.attachments.map(a => cattHtml(a, c.id, editing)).join('')}</div>` : '';
  const main = editing ? `<div class="cedit"><textarea class="c-edit-input" data-cid="${c.id}" rows="2">${esc(decodeMentions(c.body, U))}</textarea><div class="mpick hidden"></div>${files}<div class="cbar"><span class="spacer"></span><button class="btn sm" data-act="c-edit-cancel">${tr('Cancel')}</button><button class="btn sm pri" data-act="c-edit-save" data-cid="${c.id}">${tr('Save')}</button></div></div>`
    : `${ro ? '' : replyQuoteHtml(c, 'c')}${c.body ? `<div class="cbody">${commentBody(c.body, U, taskById(c.task_id || S.sel)?.list_id)}</div>` : ''}${files}${sugHtml(c, ro)}${reactHtml(c, ro)}`;
  // 2.5.1 (#395): the author's avatar opens the same card as an @mention (only in the comment list, not read-only copies)
  const cav = ro ? av(c.user_id, uname(c.user_id, U)) : `<button type="button" class="cmav" data-mcard="${c.user_id}" data-mname="${esc(uname(c.user_id, U))}" aria-haspopup="dialog" title="${esc(tr('Show {0}', uname(c.user_id, U)))}">${av(c.user_id, uname(c.user_id, U))}</button>`;
  return `<div class="cm ${isNew ? 'new' : ''}${rxShow('k' + c.id)}" data-cid="${c.id}" data-mid="c:${c.id}">${cav}<div class="cmain"><div class="chead"><b>${esc(uname(c.user_id, U))}</b>${isAgentUser(c.user_id) ? agentBadge() : ''}<span class="muted">${fmtWhen(c.created_at)}${c.edited_at ? ' · ' + tr('edited') : ''}</span>${acts}</div>${main}</div></div>`;
}
function timelineItems(ro = false) {
  const T = S.tl, soc = cmSocial(taskById(T.id));
  if (T.err) return `<div class="muted cmempty">${T.err === 'offline' ? tr('Comments and activity are only available online.') : esc(T.err)}</div>`;
  if (!T.comments) return `<div class="muted cmempty">${tr('Loading…')}</div>`;
  const U = T.users || {};
  const items = [...T.comments.map(c => ({at: c.created_at, c, ro})), ...(showAct() || !soc ? (soc ? T.activity || [] : tlForeign(taskById(T.id))).map(a => ({at: a.created_at, a})) : [])]
    .sort((x, y) => new Date(x.at) - new Date(y.at) || (x.c ? 1 : 0) - (y.c ? 1 : 0));
  if (!items.length) return soc || cmSplitOn(taskById(T.id)) ? `<div class="muted cmempty">${tr('No comments yet.')}</div>` : '';  // 2.31.0 (#344): the split keeps its area
  const lastC = [...items].reverse().find(it => it.c);
  if (cmtNew()) items.reverse();  // 2.4.2 (#386)
  // 2.13.2 (#478 F5): comments of the same author in a row (within 15 minutes) are one group: only the first shows the
  // picture, name and badge
  const grp = (it, i) => { const p = items[i - 1]; return !!(it.c && p?.c && p.c.user_id === it.c.user_id && Math.abs(new Date(it.at) - new Date(p.at)) < 900000); };
  return items.map((it, i) => it.c ? commentHtml(it.c, U, it.ro).replace('<div class="cm ', `<div class="cm ${it === lastC ? 'last ' : ''}${grp(it, i) ? 'grp ' : ''}`) : `<div class="actl"><span>${actText(it.a, U)}</span><time>${fmtWhen(it.a.created_at)}</time></div>`).join('');
}
// 2.0.7: the folded history of a private list (as in 2.0.5): all changes of the task, oldest first
function histItems() {
  const T = S.tl;
  if (T.err) return `<div class="muted cmempty">${T.err === 'offline' ? tr('Comments and activity are only available online.') : esc(T.err)}</div>`;
  if (!T.activity) return `<div class="muted cmempty">${tr('Loading…')}</div>`;
  return T.activity.map(a => `<div class="actl"><span>${actText(a, T.users || {})}</span><time>${fmtWhen(a.created_at)}</time></div>`).join('');
}
function composerFiles(tid) {
  return (S.cfiles[tid] || []).map((f, i) => `<span class="cfile">${ic(/^image\//.test(f.type) ? 'clip' : 'file', 's')}<span>${esc(f.name || tr('Image'))}</span><button data-act="c-file-rm" data-i="${i}" title="${tr('Remove')}">${ic('x', 's')}</button></span>`).join('');
}
function timelineHtml(t) {
  const n = S.tl.id === t.id && S.tl.comments ? S.tl.comments.length : t.comment_count || 0, soc = cmSocial(t);
  const nw = cmtNew(), top = nw && cmtOn() && t.id > 0 && !t.context, split = cmSplitOn(t);
  // 2.31.0 (#1054): order and history sit in a small "…" menu (were two big switches); "Comments only" says so in the head.
  // (#344) the desktop split folds its area with the arrow at the end
  return `<h5 class="cmhead"><span>${tr('Comments')}</span><span class="c" id="d-tl-count">${n || ''}</span>${soc && !showAct() ? `<span class="cmmode">${tr('Comments only')}</span>` : ''}<span class="spacer"></span><button type="button" class="iconbtn cmmenu" data-act="tl-menu" aria-haspopup="menu" aria-label="${esc(tr('Comment options'))}" title="${esc(tr('Comment options'))}">${ic('dots', 's')}</button>${split ? `<button type="button" class="iconbtn dsfoldb" data-act="cm-fold" aria-controls="d-cpane" aria-expanded="${!dsFold()}" aria-label="${esc(dsFold() ? tr('Show the comments') : tr('Fold the comments'))}" title="${esc(dsFold() ? tr('Show the comments') : tr('Fold the comments'))}">${ic('chev', 's')}</button>` : ''}</h5>
    ${top ? cmComposer(t, true) : ''}<div class="cms" id="d-tl-items">${S.tl.id === t.id ? timelineItems() : `<div class="muted cmempty">${tr('Loading…')}</div>`}</div>
    ${soc ? typingHtml(taskTypers(t), 'd-typing') : ''}`;
}
// 2.0.6: the comment box at the bottom edge of the task panel, visible while scrolling (sticky with the
// footer); one line until it is used (focus, text or files), then the bar with files and Send
function cmComposer(t, top = false) {  // top: 2.4.2 (#386) newest first, the box above the newest comment
  const soc = cmSocial(t), used = !!S.drafts[t.id] || !!(S.cfiles[t.id] || []).length;
  return `<div class="dcomp ${top ? 'dctop' : ''}">${replyBarHtml('c:' + t.id)}<div class="ccomp ${used ? 'used' : ''}"><textarea id="c-input" rows="1" name="kalmido-comment" autocomplete="off" data-form-type="other" data-lpignore="true" placeholder="${soc ? tr('Write a comment… (@ mentions someone)') : tr('Write a comment…')}" aria-label="${tr('Comment')}">${esc(S.drafts[t.id] || '')}</textarea>
      <div class="mpick hidden"></div>
      <div class="cfiles" id="c-files">${composerFiles(t.id)}</div>
      <div class="cbar"><label class="iconbtn" title="${tr('Attach files')}">${ic('clip', 's')}<input type="file" id="c-file" multiple hidden></label><span class="muted chint">${isMobile() ? '' : tr('Ctrl+Enter sends')}</span><span class="spacer"></span><button class="btn sm pri" data-act="c-send">${ic('send', 's')} ${tr('Send')}</button></div></div></div>`;
}
function drawTimeline() {
  if (S.tl.id !== S.sel) return;
  const box = $('#d-tl-items'); if (box) patchKids(box, timelineItems());  // 2.12.2 (#451): only changed / new comments
  const hb = $('#d-hist-items'); if (hb) hb.innerHTML = histItems();
  const n = $('#d-tl-count'); if (n) n.textContent = S.tl.comments?.length || '';
  const n2 = $('#d-jump-count'); if (n2) n2.textContent = S.tl.comments?.length || '';
  const t = taskById(S.sel), want = !!t && (cmSplitOn(t) || (S.tl.comments?.length || 0) > 0 || cmSocial(t) || tlForeign(t).length > 0);
  if (t && $('#detail .dcomp') && !!$('#d-tl') !== want) {  // #315: the list appears with the first comment (or goes with the last)
    const f = document.activeElement?.id === 'c-input'; renderDetail(); if (f) $('#c-input')?.focus();
  }
  if (S.tlScroll === S.sel && S.tl.comments) { S.tlScroll = null; const b = $('#d-tl-items'); (cmtNew() ? $('#d-tl') : b?.lastElementChild)?.scrollIntoView({block: 'nearest'}); }  // opened from a comment (#386: newest first = the top)
}
const mdIsLong = s => { s = String(s || ''); return s.split('\n').length > 10 || s.length > 900; };  // 2.27.0 (#994): 8 -> 10 lines, 640 -> 900 characters
async function loadTimeline(id) {
  if (!(id > 0) || !(cmtOn() || collab()) || S.tasks.get(id)?.context) return;  // 2.0.7: collab = the history
  const my = S.tlSeq = (S.tlSeq || 0) + 1, v = S.v;
  let j;
  try { j = await rawFetch('GET', `/api/tasks/${id}/timeline`); }
  catch (e) {
    if (e.message === 'auth' || my !== S.tlSeq || S.sel !== id) return;
    if (S.tl.id !== id || !S.tl.comments) S.tl = {id, v, err: e instanceof Offline ? 'offline' : e.message};
    drawTimeline(); return;
  }
  if (my !== S.tlSeq || S.sel !== id) return;
  const first = S.tl.id !== id, fresh = first || !S.tl.comments;  // 2.31.0: fresh = the comments arrive for the first time
  const seen = S.tl.id === id ? S.tl.seen : j.seen;  // "new" marks stay while the panel is open
  S.tl = {...j, id, v, seen};
  if (S.cedit && !j.comments.some(c => c.id === S.cedit)) S.cedit = null;
  drawTimeline();
  const t = S.tasks.get(id), top = Math.max(0, ...j.comments.map(c => c.id));
  if (t && (t.unread || t.comment_count !== j.comments.length)) { t.unread = 0; t.comment_count = j.comments.length; viewSafeRender(); }
  if (top > (j.seen || 0)) rawFetch('POST', `/api/tasks/${id}/seen`).catch(() => {});
  // 2.24.0 (UX-41): opened with an unread comment of someone else: straight to the comments
  // 2.31.0 (#344): the desktop split shows the comments anyway: its area starts at the newest one
  const pane = fresh && $('#detail.dsplit #d-cpane');
  if (pane && !cmtNew()) pane.scrollTop = pane.scrollHeight;
  else if (first && j.comments.some(c => c.id > (j.seen || 0) && c.user_id !== S.me?.id)) setTimeout(() => { if (S.sel === id) $('#d-tl')?.scrollIntoView?.({block: 'start', behavior: reducedMotion() ? 'auto' : 'smooth'}); }, 60);
}
async function capi(method, url, body) {  // comments: never queued, clear message when offline
  try { return await rawFetch(method, url, body); }
  catch (e) {
    if (e instanceof Offline) toast(tr('You are offline: the comment was not sent and stays in the box'));
    else if (e.message !== 'auth') toast(e.message);
    throw e;
  }
}
async function sendComment() {
  const tid = S.sel, ta = $('#c-input'); if (!ta || !tid) return;
  if (tid < 0) { toast(tr('Task is still syncing, try again in a moment')); return; }
  const raw = ta.value.trim(), files = S.cfiles[tid] || [];
  if (!raw && !files.length) { ta.focus(); return; }
  const big = files.find(f => f.size > 50 * 1024 * 1024);
  if (big) { toast(tr('{0} is larger than 50 MB', big.name)); return; }
  const text = encodeMentions(raw, S.tl.id === tid ? S.tl.people : []);
  const rto = replyTo('c:' + tid);  // 2.33.0 (#1076)
  let payload = {body: text, ...(rto ? {reply_to: rto} : {})};
  if (files.length) { payload = new FormData(); payload.append('body', text); if (rto) payload.append('reply_to', rto); files.forEach((f, i) => payload.append('file', f, f.name || `bild-${Date.now()}-${i}.png`)); }
  const btn = $('[data-act="c-send"]'); if (btn) btn.disabled = true;
  try { await capi('POST', `/api/tasks/${tid}/comments`, payload); }
  catch { return; }
  finally { if (btn) btn.disabled = false; }
  delete S.drafts[tid]; delete S.cfiles[tid]; replySent('c:' + tid);
  if (S.sel === tid) { const i = $('#c-input'); if (i) { i.value = ''; autosize(i); } const f = $('#c-files'); if (f) f.innerHTML = ''; }
  await loadTimeline(tid);
  const box = $('#d-tl-items'); if (box) (cmtNew() ? box.firstElementChild : box.lastElementChild)?.scrollIntoView({block: 'nearest'});
}
function addCommentFiles(files) {
  files = noEmpty(files); if (!files.length || !S.sel) return;
  (S.cfiles[S.sel] ||= []).push(...files);
  const f = $('#c-files'); if (f) { f.innerHTML = composerFiles(S.sel); f.closest('.ccomp')?.classList.add('used'); }
}
// @mention picker: people who can see the task (from the timeline), without me
function mentionState(ta) {
  const pick = ta.parentElement.querySelector('.mpick'); if (!pick) return null;
  const pre = ta.value.slice(0, ta.selectionStart), m = pre.match(/(?:^|\s)@([^\s@<>]{0,30}(?: [^\s@<>]{0,30})?)$/u);
  const people = (ta.id === 'tc-in' || ta.classList.contains('tc-edit') ? (S.tc.room?.members || []).map(m => ({id: m.id, user_id: m.id, name: m.name})) : (S.tl.people || [])).filter(p => !S.me || p.id !== S.me.id);  // 2.17.0: the team chat's members
  if (!m || !people.length) return {pick, items: []};
  const q = m[1].toLowerCase();
  // 2.26.0 (#928): agents only where the list owner opened them to members (else the server ignores the mention)
  const tc = ta.id === 'tc-in' || ta.classList.contains('tc-edit'), ll = listById(tc ? S.tc.room?.list_id : taskById(S.sel)?.list_id);
  const agOk = !ll || ll.agents_open !== false;
  const items = people.filter(p => agOk || !(p.agent || agentById(p.user_id ?? p.id))).filter(p => { const n = p.name.toLowerCase(); return n.startsWith(q) || n.split(/\s+/).some(w => w.startsWith(q)); }).slice(0, 6);
  return {pick, items, start: pre.length - m[1].length - 1};
}
function mentionUpdate(ta) {
  if (ta.id !== 'tc-in' && !ta.classList.contains('tc-edit') && !cmSocial(taskById(S.sel))) { if (S.mp) mentionClose(); return; }  // #315: nobody to mention in a private list
  const st = mentionState(ta); if (!st) return;
  S.mp = st.items.length ? {ta, ...st, i: 0} : null;
  st.pick.classList.toggle('hidden', !st.items.length);
  // 2.17.2 (review): a listbox of options; the box points at the highlighted one (screen readers follow the arrow keys)
  const pid = st.pick.id || (st.pick.id = 'mp' + (++mpSeq));
  st.pick.setAttribute('role', 'listbox'); if (!st.pick.hasAttribute('aria-label')) st.pick.setAttribute('aria-label', tr('Mention someone'));
  st.pick.innerHTML = st.items.map((p, i) => `<button type="button" role="option" id="${pid}-o${i}" tabindex="-1" aria-selected="${i === 0}" class="${i === 0 ? 'on' : ''}" data-act="mention-pick" data-i="${i}">${av(p.user_id ?? p.id, p.name)}${esc(p.name)}</button>`).join('');
  mentionAria(ta, st.items.length ? pid + '-o0' : '', pid);
}
let mpSeq = 0;
function mentionAria(ta, act, pid) {
  if (pid) ta.setAttribute('aria-controls', pid);
  if (act) ta.setAttribute('aria-activedescendant', act); else ta.removeAttribute('aria-activedescendant');
}
function mentionPick(i) {
  const mp = S.mp; if (!mp) return;
  const p = mp.items[i], ta = mp.ta, caret = ta.selectionStart;
  ta.value = ta.value.slice(0, mp.start) + '@' + p.name + ' ' + ta.value.slice(caret);
  const pos = mp.start + p.name.length + 2;
  ta.focus(); ta.setSelectionRange(pos, pos);
  mp.pick.classList.add('hidden'); S.mp = null; mentionAria(ta, '');
  if (ta.id === 'c-input') S.drafts[S.sel] = ta.value;
  autosize(ta);
}
function mentionClose() { if (S.mp) { S.mp.pick.classList.add('hidden'); mentionAria(S.mp.ta, ''); S.mp = null; } }
document.addEventListener('keydown', e => {
  const t = e.target;
  if (!(t.id === 'c-input' || t.classList?.contains('c-edit-input') || t.id === 'tc-in' || t.classList?.contains('tc-edit'))) return;
  if (S.mp && S.mp.ta === t) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); S.mp.i = (S.mp.i + (e.key === 'ArrowDown' ? 1 : -1) + S.mp.items.length) % S.mp.items.length;
      $$('button', S.mp.pick).forEach((b, i) => { b.classList.toggle('on', i === S.mp.i); b.setAttribute('aria-selected', i === S.mp.i); });
      mentionAria(t, S.mp.pick.id + '-o' + S.mp.i); return;
    }
    if ((e.key === 'Enter' || e.key === 'Tab') && !e.isComposing) { e.preventDefault(); e.stopImmediatePropagation(); mentionPick(S.mp.i); return; }
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); mentionClose(); return; }
  }
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault(); e.stopImmediatePropagation();
    if (t.id === 'c-input') sendComment(); else $(`[data-act="c-edit-save"][data-cid="${t.dataset.cid}"]`)?.click();
  }
}, true);
document.addEventListener('mousedown', e => { if (e.target.closest('.mpick')) e.preventDefault(); });  // keep the caret in the box

// ------------------------------------------------------------------ 2.33.0 (#1076 / #1080): jump to one message
// window.msgJump({art, id, task, chat, agent}) -- art 'c' = a task comment (task = its task id), 't' = a team chat message
// (chat = its room id), 'a' = an agent chat message (agent = the agent's id). Opens the place (the task with its comments,
// the conversation), loads older pages until the message is there, scrolls to it and marks it for a moment (.msg-hit).
// Gone (deleted, trimmed, no rights): "Message not found". Every message in the DOM carries data-mid="<art>:<id>".
// Used by the reply quotes (#1076) and the search hits (#1080). Returns true when the message was found.
const msgWait = async (fn, ms = 8000) => { const t0 = Date.now(); for (;;) { const v = fn(); if (v) return v; if (Date.now() - t0 > ms) return null; await new Promise(r => setTimeout(r, 100)); } };
function msgHit(el) {
  if (!el) return false;
  $$('.msg-hit').forEach(x => x.classList.remove('msg-hit'));
  try { el.scrollIntoView?.({block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth'}); } catch { try { el.scrollIntoView?.(); } catch { /* old browsers */ } }
  el.classList.add('msg-hit');
  clearTimeout(msgHit.t); msgHit.t = setTimeout(() => $$('.msg-hit').forEach(x => x.classList.remove('msg-hit')), 1600);
  return true;
}
const msgMissing = () => { toast(tr('Message not found')); return false; };
async function msgJump(o = {}) {
  const art = o.art, id = +o.id; if (!id || !['c', 't', 'a'].includes(art)) return msgMissing();
  const sel = `[data-mid="${art}:${id}"]`;
  if (art === 'c') {
    const tid = +o.task; if (!tid) return msgMissing();
    if (S.sel !== tid) { if (!taskById(tid)) { try { (S.extra ||= []).push(await rawFetch('GET', `/api/tasks/${tid}`)); } catch { return msgMissing(); } } openDetail(tid); }
    if (!await msgWait(() => S.sel === tid && S.tl.id === tid && (S.tl.comments || S.tl.err))) return msgMissing();
    if (!(S.tl.comments || []).some(c => c.id === id)) return msgMissing();
    if ($('#detail.dsfold')) dsFoldToggle(false);
    return msgHit(await msgWait(() => $('#detail ' + sel), 3000)) || msgMissing();
  }
  if (art === 't') {
    const rid = +o.chat; if (!rid || !teamOn()) return msgMissing();
    if (S.route.mod !== 'team' || S.tc.rid !== rid) go('team/' + rid);
    if (!await msgWait(() => S.tc.rid === rid && S.tc.room)) return msgMissing();
    for (let n = 0; n < 60 && !S.tc.msgs.some(m => m.id === id) && S.tc.more && S.tc.msgs.length && S.tc.msgs[0].id > id; n++) { await loadRoom(rid, true); if (S.tc.rid !== rid) return false; }
    if (!S.tc.msgs.some(m => m.id === id && !m.deleted)) return msgMissing();
    tcPatch(); S.tc.fitUntil = 0;
    return msgHit(await msgWait(() => $('#tc-msgs ' + sel), 3000)) || msgMissing();
  }
  const aid = +o.agent; if (!aid || !agentById(aid)) return msgMissing();
  if (S.chat.aid !== aid || !$('#chat-msgs')) chatOpen(aid);
  if (!await msgWait(() => S.chat.aid === aid && $('#chat-msgs') && (S.chat.msgs.length || S.chat.err))) return msgMissing();
  for (let n = 0; n < 60 && !S.chat.msgs.some(m => m.id === id) && S.chat.more && S.chat.msgs[0].id > id; n++) { await chatOlder(); if (S.chat.aid !== aid) return false; }
  if (!S.chat.msgs.some(m => m.id === id)) return msgMissing();
  S.chat.pin = false;
  return msgHit(await msgWait(() => $('#chat-msgs ' + sel), 3000)) || msgMissing();
}
window.msgJump = msgJump;

// ------------------------------------------------------------------ 2.33.0 (#1076): reply to one message
// Comments, team chat, agent chat. Desktop: the reply button on hover / keyboard focus (and "Reply" in a message's menu);
// phones: swipe a message to the right (not from the left edge: that is the phone's own Back gesture; only clearly
// sideways, an arrow shows how far). The reply bar sits above the box (quote, X); the answer shows a small quote above it
// (a tap jumps to the original, msgJump), a deleted original says "Message deleted". State per place:
// S.reply['c:<task>' | 't:<room>' | 'a:<agent>'] = {id, name, text}.
S.reply = {};
const replyCtx = art => art === 'c' ? (S.sel ? 'c:' + S.sel : null) : art === 't' ? (S.tc?.rid ? 't:' + S.tc.rid : null) : art === 'a' ? (S.chat?.aid ? 'a:' + S.chat.aid : null) : null;
const replyIn = art => $(art === 'c' ? '#detail #c-input' : art === 't' ? '#tc-in' : '#chat-in');
function replyMsg(art, id) {
  const m = art === 'c' ? (S.tl.comments || []).find(x => x.id === id) : art === 't' ? (S.tc.msgs || []).find(x => x.id === id) : (S.chat.msgs || []).find(x => x.id === id);
  if (!m || m.deleted) return null;
  const U = art === 'c' ? S.tl.users : art === 't' ? S.tc.users : {};
  const name = art === 'a' ? (m.from === 'agent' ? agentById(S.chat.aid)?.name || '' : tr('You')) : m.user_id === S.me?.id ? tr('You') : uname(m.user_id, U);
  let text = mdBrief(decodeMentions(m.body || '', U));
  if (!text) text = (m.attachments || [])[0]?.name || '';
  return {id, name, mine: art === 'a' ? m.from !== 'agent' : m.user_id === S.me?.id, text: text.length > 140 ? text.slice(0, 140) + '…' : text};
}
// the quote above an answer; place: the task / room / agent the message lives in
function replyQuoteHtml(m, art) {
  const q = m?.reply; if (!q || m.deleted) return '';
  if (q.deleted) return `<div class="mquote del">${ic('reply', 's')}<span>${esc(tr('Message deleted'))}</span></div>`;
  const name = q.user_id && q.user_id === S.me?.id ? tr('You') : q.name || tr('Someone');
  return `<button type="button" class="mquote" data-act="msg-jump" data-art="${art}" data-id="${q.id}" title="${esc(tr('Show the message'))}" aria-label="${esc(tr('Reply to {0}: {1}', name, q.text) + ' – ' + tr('Show the message'))}"><b>${esc(name)}</b><span>${esc(q.text)}</span></button>`;
}
const replyBtn = (cls = 'iconbtn') => `<button type="button" class="${cls} mreply" data-act="msg-reply" title="${esc(tr('Reply'))}" aria-label="${esc(tr('Reply'))}">${ic('reply', 's')}</button>`;
function replyBarHtml(ctx) {
  const r = ctx && S.reply[ctx];
  return `<div class="rbar${r ? '' : ' hidden'}" data-rbar="${esc(ctx || '')}" role="status">${r ? `${ic('reply', 's')}<span class="rbq"><b>${esc(r.mine ? tr('Reply to your own message') : tr('Reply to {0}', r.name))}</b><span>${esc(r.text)}</span></span><button type="button" class="iconbtn" data-act="reply-x" title="${esc(tr('Cancel reply'))}" aria-label="${esc(tr('Cancel reply'))}">${ic('x', 's')}</button>` : ''}</div>`;
}
function replyBarDraw(ctx) { const b = $(`[data-rbar="${ctx}"]`); if (b) b.outerHTML = replyBarHtml(ctx); }
function replyStart(art, id) {
  const ctx = replyCtx(art), r = ctx && replyMsg(art, id); if (!r) return;
  S.reply[ctx] = r; replyBarDraw(ctx);
  const ta = replyIn(art); if (!ta) return;
  ta.closest('.ccomp')?.classList.add('used');
  try { ta.focus({preventScroll: true}); } catch { ta.focus(); }
  announce(r.mine ? tr('Reply to your own message') : tr('Reply to {0}', r.name));
}
function replyCancel(ctx, focus = true) {
  if (!ctx || !S.reply[ctx]) return false;
  delete S.reply[ctx]; replyBarDraw(ctx);
  if (focus) replyIn(ctx[0])?.focus({preventScroll: true});
  return true;
}
// the reply_to of the next message of a place (null = none); sent() clears it
const replyTo = ctx => (ctx && S.reply[ctx]?.id) || null;
const replySent = ctx => { if (ctx && S.reply[ctx]) { delete S.reply[ctx]; replyBarDraw(ctx); } };
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="msg-reply"], [data-act="msg-jump"], [data-act="reply-x"]'); if (!a) return;
  e.preventDefault(); e.stopImmediatePropagation();
  if (a.dataset.act === 'reply-x') { replyCancel(a.closest('[data-rbar]')?.dataset.rbar); return; }
  if (a.dataset.act === 'msg-jump') {
    const art = a.dataset.art;
    msgJump({art, id: +a.dataset.id, task: art === 'c' ? S.sel : null, chat: art === 't' ? S.tc.rid : null, agent: art === 'a' ? S.chat.aid : null});
    return;
  }
  const host = a.closest('[data-mid]'), [art, id] = String(host?.dataset.mid || '').split(':');
  if (art && +id) replyStart(art, +id);
});
// Escape in a box with an open reply: first the reply goes (window capture: before the boxes' own Escape)
window.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.isComposing) return;
  const t = e.target, art = t.id === 'c-input' ? 'c' : t.id === 'tc-in' ? 't' : t.id === 'chat-in' ? 'a' : null;
  if (art && !S.mp && replyCancel(replyCtx(art), false)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
// phones: swipe right on a message
{
  const RSW_EDGE = 32, RSW_MIN = 56, RSW_MAX = 88;
  let sw = null;
  const swMove = e => {
    if (!sw) return;
    const t = e.touches?.[0]; if (!t) return;
    const dx = t.clientX - sw.x, dy = t.clientY - sw.y;
    if (!sw.lock) {
      if (Math.hypot(dx, dy) < 10) return;
      if (dx > 0 && dx > Math.abs(dy) * 1.6) { sw.lock = true; sw.m.classList.add('rsw'); sw.m.insertAdjacentHTML('afterbegin', `<span class="rswarr" aria-hidden="true">${ic('reply', 's')}</span>`); }
      else { swEnd(true); return; }
    }
    if (e.cancelable) e.preventDefault();
    sw.dx = Math.max(0, Math.min(RSW_MAX, dx < RSW_MIN ? dx : RSW_MIN + (dx - RSW_MIN) / 3));
    sw.m.style.transform = `translateX(${sw.dx}px)`;
    const on = sw.dx >= RSW_MIN, arr = sw.m.querySelector(':scope > .rswarr');
    if (arr && arr.classList.contains('on') !== on) { arr.classList.toggle('on', on); if (on && navigator.vibrate) navigator.vibrate(8); }
  };
  const swEnd = cancel => {
    const st = sw; sw = null; document.removeEventListener('touchmove', swMove, {passive: false});
    if (!st || !st.lock) return;
    const m = st.m, go = !cancel && st.dx >= RSW_MIN;
    m.style.transition = reducedMotion() ? 'none' : 'transform .16s ease-out'; m.style.transform = '';
    setTimeout(() => { m.style.transition = ''; m.classList.remove('rsw'); m.querySelector(':scope > .rswarr')?.remove(); }, 180);
    if (go) { const [art, id] = String(m.dataset.mid).split(':'); replyStart(art, +id); }
  };
  document.addEventListener('touchstart', e => {
    if (sw) swEnd(true);
    if (e.touches?.length !== 1) return;
    const m = e.target.closest?.('#detail .cm[data-mid], #tc-msgs .cmsg[data-mid], #chat-msgs .cmsg[data-mid]');
    if (!m || m.querySelector('.cedit, .tcedit') || e.target.closest('textarea, input, pre, table, .rxrow, .catts, .chatts, .cchoices, .cperm, [contenteditable="true"]')) return;
    const t = e.touches[0]; if (t.clientX < RSW_EDGE || t.clientX > innerWidth - RSW_EDGE) return;
    const sel = getSelection?.(); if (sel && !sel.isCollapsed && String(sel).trim()) return;
    const [art, id] = String(m.dataset.mid).split(':'); if (!replyCtx(art) || !replyMsg(art, +id)) return;
    sw = {m, x: t.clientX, y: t.clientY, dx: 0, lock: false};
    document.addEventListener('touchmove', swMove, {passive: false});
  }, {passive: true});
  document.addEventListener('touchend', () => swEnd(false), {passive: true});
  document.addEventListener('touchcancel', () => swEnd(true), {passive: true});
}
