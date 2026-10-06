/* Kalmido web client: News bundled per task, the dashboard and Settings > Tasks by e-mail.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ #452 News bundled
// News grouped per task (or list / kind) with one line of what happened ("3 comments · completed"), "Needs you"
// (approvals, proposals, mentions, assignments, follow-ups) above "For your information", "Mark read" per group, and
// "Summarize": the unread items go to an agent's chat, which answers with a short summary. Per device: bundled or the
// plain list (the toggle in the bar).
const NEWS_NEEDS = ['approval', 'proposal', 'mention', 'assign', 'take', 'followup'];
const newsBundled = () => LS.get('newsBundle', true) !== false;
function newsGroups(items) {
  const groups = new Map();
  for (const [it, i] of items) {
    const key = it.task_id && !(it.tasks || []).length ? 't' + it.task_id : it.list_id && ['share', 'role', 'unshare', 'owner', 'status'].includes(it.kind) ? 'l' + it.list_id : 'k' + it.kind + (it.kind === 'comment' ? it.actor_id : '');
    if (!groups.has(key)) groups.set(key, {key, items: [], needs: false, unread: 0, at: it.created_at});
    const g = groups.get(key);
    g.items.push([it, i]); if (NEWS_NEEDS.includes(it.kind)) g.needs = true; if (!it.read) g.unread++;
  }
  return [...groups.values()];
}
function newsSummaryLine(g) {
  const c = {};
  for (const [it] of g.items) c[it.kind] = (c[it.kind] || 0) + (it.count || 1);
  const L = {comment: n => trn('{0} comment', '{0} comments', n), mention: n => trn('{0} mention', '{0} mentions', n), assign: () => tr('assigned to you'),
    unassign: () => tr('unassigned'), complete: () => tr('completed'), newtask: n => trn('{0} new task', '{0} new tasks', n), status: () => tr('status changed'),
    share: () => tr('shared with you'), approval: n => trn('{0} approval waits', '{0} approvals wait', n), proposal: () => tr('a proposal is ready'),
    followup: () => tr('follow up today'), unblock: () => tr('unblocked'), take: () => tr('taken'), role: () => tr('your role changed'), owner: () => tr('you own it now'),
    unshare: () => tr('removed'), usage: () => tr('usage limit'), errreport: () => tr('new error'), agentjoin: () => tr('an agent joined')};
  return Object.entries(c).map(([k, n]) => (L[k] || (() => k))(n)).join(' · ');
}
function newsGroupHtml(g, pop) {
  const [first] = g.items[0], U = S.nf.users;
  const title = first.task_id && !(first.tasks || []).length ? esc(first.task_title || '') : first.list_id && g.key[0] === 'l' ? esc(newsListName(first)) : newsText(first, U);
  const actors = [...new Set(g.items.flatMap(([it]) => it.actors || [it.actor_id]).filter(Boolean))].slice(0, 4);
  const ids = g.items.flatMap(([it]) => it.ids || [it.id]);
  const open = g.items.length === 1 ? (pop ? 'data-bp="open"' : 'data-act="news-open"') + ` data-i="${g.items[0][1]}"` : `data-act="news-group" data-g="${esc(g.key)}"`;
  const exp = S.nf.openG === g.key;
  return `<div class="ngroup ${g.unread ? 'unread' : ''} ${g.needs ? 'needs' : ''}" data-gk="${esc(g.key)}">
    <div class="nghead"><div class="ngav">${actors.map(a => av(a, uname(a, U), 'avatar sm')).join('')}</div>
      <div class="ngmain" role="button" tabindex="0" ${open} ${g.items.length > 1 ? `aria-expanded="${exp}"` : ''}><div class="ngt">${title}${g.items.length > 1 ? `<span class="ngn">${g.items.length}</span>` : ''}</div><div class="ngs muted">${esc(newsSummaryLine(g))} · <time>${esc(relTime(g.at))}</time></div></div>
      ${g.unread ? `<button type="button" class="iconbtn" data-act="news-gread" data-ids="${ids.join(',')}" title="${esc(tr('Mark read'))}" aria-label="${esc(tr('Mark read') + ': ' + title.replace(/<[^>]+>/g, ''))}">${ic('check', 's')}</button>` : ''}</div>
    ${exp && g.items.length > 1 ? `<div class="nlist ngitems">${g.items.map(([it, i]) => newsItemHtml(it, i, pop)).join('')}</div>` : ''}</div>`;
}
function newsBundledHtml(vis, pop) {
  // 2.18.0 (#652): the two sections are h2 (the page's h1 is the header title; the bell's panel has no heading above them)
  const gs = newsGroups(vis), needs = gs.filter(g => g.needs), info = gs.filter(g => !g.needs);
  return (needs.length ? `<section class="nsect" aria-labelledby="ns-need"><h2 id="ns-need" class="nsh">${tr('Needs you')}<span class="c">${needs.length}</span></h2>${needs.map(g => newsGroupHtml(g, pop)).join('')}</section>` : '')
    + (info.length ? `<section class="nsect" aria-labelledby="ns-info"><h2 id="ns-info" class="nsh">${tr('For your information')}<span class="c">${info.length}</span></h2>${info.map(g => newsGroupHtml(g, pop)).join('')}</section>` : '');
}
async function newsGroupRead(ids) {
  try { await rawFetch('POST', '/api/news/read', {ids}); } catch (e) { toast(e.message); return; }
  for (const it of S.nf.items || []) if ((it.ids || [it.id]).some(x => ids.includes(x))) { it.read = true; it.keep = S.nf.unread; }
  announce(tr('Marked read')); render();
  await loadNews().catch(() => {}); render();  // the counts from the server (an item may stand for several)
}
// "Summarize": the unread News as plain lines to an agent's chat
function newsSummarize(anchor) {
  const ags = (S.agents || []).filter(a => a.enabled);
  const items = (S.nf.items || []).filter(it => !it.read);
  if (!items.length) { toast(tr('No unread news')); return; }
  const send = async a => {
    const U = S.nf.users;
    const lines = items.slice(0, 120).map(it => '- ' + newsText(it, U).replace(/<[^>]+>/g, '') + (it.task_title ? ` (${it.task_title})` : '') + (it.excerpt ? `: ${String(it.excerpt).replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, U)).slice(0, 160)}` : ''));
    const text = tr('Please summarize my {0} unread news items in at most 5 short lines: what needs me first, then the rest.', items.length) + '\n\n' + lines.join('\n');
    try { await rawFetch('POST', `/api/agents/${a.id}/chat`, {body: text.slice(0, 7900)}); } catch (e) { toast(e.message); return; }
    closePop(); chatOpen(a.id); toast(tr('Sent to {0}', a.name));
  };
  if (ags.length === 1) send(ags[0]);
  else menu(anchor, ags.map(a => ({label: tr('Ask {0}', a.name), icon: 'bot', fn: () => send(a)})));
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="news-gread"],[data-act="news-group"],[data-act="news-bundle"],[data-act="news-sum"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  if (a.dataset.act === 'news-gread') {  // 2.17.2: the focus moves on to the group in the same place (or the last one)
    const gs = $$('#view .ngroup, .bplist .ngroup'), gi = gs.indexOf(a.closest('.ngroup')), inPop = !!a.closest('.bplist');
    newsGroupRead(a.dataset.ids.split(',').map(Number)).then(() => { if (!document) return; const n = $$((inPop ? '.bplist' : '#view') + ' .ngroup .ngmain'); (n[Math.min(gi, n.length - 1)] || $('#view h1, #top h1'))?.focus?.(); });
  }
  else if (a.dataset.act === 'news-group') { S.nf.openG = S.nf.openG === a.dataset.g ? null : a.dataset.g; render(); if ($('#pop .bpop')) { const p = $('#pop'); p.innerHTML = bellPopHtml(); } }
  else if (a.dataset.act === 'news-bundle') { LS.set('newsBundle', !newsBundled()); render(); if ($('#pop .bpop')) $('#pop').innerHTML = bellPopHtml(); }
  else if (a.dataset.act === 'news-sum') newsSummarize(a);
}, true);
document.addEventListener('keydown', e => { const g = e.target.closest?.('.ngmain[data-act="news-group"]'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.click(); } });

// ------------------------------------------------------------------ #475 the dashboard (a tap on the logo)
// Small cards, in your order, each can be hidden ("Customize": ↑ ↓ and a switch per card, keyboard too); stored with your
// settings (all devices). What waits for you, today, bundled news, team chat, projects, pinned tasks, notes, agents, a
// few numbers and a search field.
const DASH = [['wait', N_('Waiting for you'), 'hourglass'], ['today', N_('Today'), 'sun'], ['news', N_('News'), 'bell'], ['chat', N_('Team chat'), 'comment'],
  ['projects', N_('Projects'), 'brief'], ['pinned', N_('Pinned|view'), 'pin'], ['notes', N_('Notes'), 'edit'], ['agents', N_('Agents'), 'bot'],
  ['stats', N_('Statistics'), 'chart'], ['search', N_('Search'), 'search'], ['family', N_('Family'), 'family']];
S.dash = {custom: false};
function dashPref() {
  let o = {}; try { o = JSON.parse(S.settings?.dashboard || '{}') || {}; } catch { o = {}; }
  const order = [...(o.order || []).filter(k => DASH.some(d => d[0] === k)), ...DASH.map(d => d[0]).filter(k => !(o.order || []).includes(k))]
    .filter(k => k !== 'family' || famOn());  // 2.19.0 (#653): only with the module
  return {order, hidden: new Set(o.hidden || [])};
}
async function dashSave(order, hidden) {
  const v = JSON.stringify({order, hidden: [...hidden]});
  S.settings.dashboard = v; renderView();
  try { await api('PATCH', '/api/settings', {dashboard: v}); } catch { /* api() said it */ }
}
function dashCard(k) {
  const [_, name, icon] = DASH.find(d => d[0] === k), t0 = today();
  const card = (body, more = '', n = '') => `<section class="dcard dc-${k}" aria-labelledby="dh-${k}"><h3 id="dh-${k}">${ic(icon, 's')}<span>${tr(name)}</span>${n !== '' ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span>${more}</h3>${body}</section>`;
  const tasksList = ts => ts.length ? `<ul class="dtl">${ts.slice(0, 6).map(t => `<li><button type="button" class="chk p${t.priority}" data-act="toggle" data-id="${t.id}" role="checkbox" aria-checked="false" aria-label="${esc(tr('Complete: {0}', t.title))}"></button><a href="#t/${t.id}" class="dtt">${esc(t.title)}</a>${t.due ? `<span class="dt ${dueClass(t)}">${esc(dayLabel(t.due))}${t.due_time ? ' ' + t.due_time : ''}</span>` : ''}</li>`).join('')}</ul>${ts.length > 6 ? `<p class="muted dmore">${tr('{0} more', ts.length - 6)}</p>` : ''}` : '';
  if (k === 'wait') {
    const js = waitJobs ? waitJobs() : [], ments = (S.nf.items || []).filter(it => !it.read && ['mention', 'assign', 'approval', 'proposal'].includes(it.kind));
    const rows = [...js.map(j => `<li><a href="#agents">${hdot('waiting')}<span class="dwt">${esc(tr('{0} waits for you', j.agent_name))}: ${esc(j.title)}</span></a></li>`),
      ...ments.slice(0, 5).map(it => `<li><a href="${it.task_id ? '#t/' + it.task_id : '#news'}">${ic(NEWS_ICON[it.kind] || 'bell', 's')}<span class="dwt">${newsText(it, S.nf.users)}${it.task_title ? ' · ' + esc(it.task_title) : ''}</span></a></li>`)];
    return card(rows.length ? `<ul class="dwl">${rows.join('')}</ul>` : `<p class="muted">${tr('Nothing waits for you.')}</p>`, '', rows.length || '');
  }
  if (k === 'today') {
    const ts = openTasks().filter(t => !t.parent_id && t.due && t.due <= t0).sort((a, b) => dueKey(a).localeCompare(dueKey(b)) || b.priority - a.priority);
    const ev = (S.calToday || []).length;
    return card(tasksList(ts) || `<p class="muted">${tr('Nothing left for today.')}</p>`, `<a class="linkbtn" href="#today">${tr('Open')}</a>`, ts.length || '') ;
  }
  if (k === 'news') {
    if (S.nf.items === null || S.nf.sig !== (S.news?.sig ?? '')) { if (!S.nf.loading) loadNews().then(() => { if (S.route.mod === 'home') renderView(); }); }
    const vis = (S.nf.items || []).map((it, i) => [it, i]).filter(([it]) => !it.read);
    const gs = newsGroups(vis).slice(0, 5);
    return card(gs.length ? `<div class="dng">${gs.map(g => newsGroupHtml(g, false)).join('')}</div>` : `<p class="muted">${tr('No unread news')}</p>`, `<a class="linkbtn" href="#news">${tr('Show all')}</a>`, S.news?.unread || '');
  }
  if (k === 'chat') {
    if (!teamOn()) return '';
    if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.route.mod === 'home') renderView(); }); }
    const rs = (S.tc.rooms || []).filter(r => r.last).slice(0, 4);
    return card(rs.length ? `<ul class="dwl">${rs.map(r => `<li><a href="#team/${r.id}">${roomIcon(r)}<span class="dwt"><b>${esc(roomName(r))}</b> ${esc(r.last.text)}</span>${r.unread ? `<span class="nbadge">${r.unread}</span>` : ''}</a></li>`).join('')}</ul>` : `<p class="muted">${tr('No messages yet')}</p>`, `<a class="linkbtn" href="#team">${tr('Open')}</a>`, S.team?.unread || '');
  }
  if (k === 'projects') {
    const ps = S.lists.filter(l => l.kind === 'project' && !l.archived);
    if (!ps.length) return '';
    return card(`<ul class="dpl">${ps.slice(0, 6).map(l => { const all = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.parent_id), dn = all.filter(t => t.status === 2).length, pc = all.length ? Math.round(dn / all.length * 100) : 0;
      return `<li><a href="#l/${l.id}"><span class="dpn">${esc(lname(l))}</span><span class="dpb" role="img" aria-label="${esc(tr('{0} % done', pc))}"><i style="width:${pc}%"></i></span><span class="dpp">${pc} %</span></a></li>`; }).join('')}</ul>`, '', ps.length);
  }
  if (k === 'pinned') {
    const ts = openTasks().filter(t => t.pinned && !t.parent_id);
    return ts.length ? card(tasksList(ts), `<a class="linkbtn" href="#pinned">${tr('Open')}</a>`, ts.length) : '';
  }
  if (k === 'notes') {
    const ns = (S.notes || []).slice(0, 5);
    return ns.length ? card(`<ul class="dwl">${ns.map(n => `<li><a href="#note/${n.id}">${ic('edit', 's')}<span class="dwt"><b>${esc(n.title)}</b> <span class="muted">${esc(lname(listById(n.list_id)) || '')} · ${esc(relTime(n.updated_at))}</span></span></a></li>`).join('')}</ul>`) : '';
  }
  if (k === 'agents') {
    const ags = (S.agents || []).filter(a => a.enabled);
    return ags.length ? card(`<ul class="dwl">${ags.map(a => `<li><a href="#agents/${a.id}">${hdot(agentHst(a))}<span class="dwt">${esc(agentHstLine(a))}</span></a></li>`).join('')}</ul>`) : '';
  }
  if (k === 'stats') {
    const done7 = [...S.tasks.values()].filter(t => t.status === 2 && t.completed_at && t.completed_at.slice(0, 10) >= addDays(t0, -6)).length;
    const doneT = [...S.tasks.values()].filter(t => t.status === 2 && t.completed_at && t.completed_at.slice(0, 10) === t0).length;
    const over = openTasks().filter(t => !t.parent_id && t.due && t.due < t0).length;
    const tile = (n, l, href) => `<a class="dtile" href="${href}"><b>${n}</b><span>${esc(l)}</span></a>`;
    return card(`<div class="dtiles">${tile(doneT, tr('done today'), '#done')}${tile(done7, tr('done in 7 days'), '#stats')}${tile(over, tr('overdue'), '#today')}${tile(openTasks().filter(t => !t.parent_id).length, tr('open'), '#all')}</div>`);
  }
  if (k === 'family') {  // 2.19.0 (#653): the next birthdays, whose turn it is, today's meal
    if (!famOn()) return '';
    const d = famData(), t0x = today(), rows = [];
    for (const t of d.occ.filter(x => daysTo(x.due) <= 14).slice(0, 3)) rows.push(`<li><a href="#t/${t.id}"><span aria-hidden="true">${t.fam.kind === 'birthday' ? '🎂' : '💍'}</span><span class="dwt"><b>${esc(t.fam.name || t.title)}</b> ${esc([occWhat(t), daysWord(daysTo(t.due))].filter(Boolean).join(' · '))}</span></a></li>`);
    for (const t of d.rots.filter(x => x.assignee_id === S.me?.id).slice(0, 3)) rows.push(`<li><a href="#t/${t.id}">${ic('turns', 's')}<span class="dwt">${esc(tr('Your turn: {0}', t.title))}</span></a></li>`);
    for (const t of d.meals.filter(x => x.due === t0x).slice(0, 2)) rows.push(`<li><a href="#t/${t.id}">${ic('meal', 's')}<span class="dwt">${esc(tr('Today: {0}', t.title))}</span></a></li>`);
    return card(rows.length ? `<ul class="dwl">${rows.join('')}</ul>` : `<p class="muted">${tr('Nothing coming up.')}</p>`, `<a class="linkbtn" href="#family">${tr('Open')}</a>`);
  }
  if (k === 'search') {
    return card(`<form class="dsearch" data-dsearch role="search"><input id="dash-q" type="search" placeholder="${esc(tr('Jump, create, ask an agent…'))}" aria-label="${esc(tr('Search and commands'))}" autocomplete="off"><button type="submit" class="btn sm">${ic('search', 's')}<span class="sr">${tr('Search')}</span></button></form>`);
  }
  return '';
}
function viewHome() {
  const {order, hidden} = dashPref();
  const greet = (() => { const h = new Date().getHours(); return h < 11 ? tr('Good morning, {0}', S.me?.display_name || '') : h < 18 ? tr('Hello, {0}', S.me?.display_name || '') : tr('Good evening, {0}', S.me?.display_name || ''); })();
  if (S.dash.custom) {
    return `<div class="dash"><div class="dashhead"><h2>${tr('Customize the dashboard')}</h2><span class="spacer"></span><button type="button" class="btn sm pri" data-act="dash-done">${tr('Done')}</button></div>
      <ol class="dcust" aria-label="${esc(tr('Cards'))}">${order.map((k, i) => { const [_, n, icon] = DASH.find(d => d[0] === k); return `<li data-k="${k}">${ic(icon, 's')}<span class="dcl">${tr(n)}</span>
        <button type="button" class="iconbtn" data-act="dash-mv" data-k="${k}" data-d="-1" ${i ? '' : 'disabled'} aria-label="${esc(tr('Move up') + ': ' + tr(n))}">${ic('up', 's')}</button>
        <button type="button" class="iconbtn" data-act="dash-mv" data-k="${k}" data-d="1" ${i < order.length - 1 ? '' : 'disabled'} aria-label="${esc(tr('Move down') + ': ' + tr(n))}">${ic('down', 's')}</button>
        <label class="swc"><input type="checkbox" data-dshow="${k}" ${hidden.has(k) ? '' : 'checked'}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show {0}', tr(n)))}</span></label></li>`; }).join('')}</ol>
      <button type="button" class="linkbtn" data-act="dash-reset">${tr('Reset to defaults')}</button></div>`;
  }
  const cards = order.filter(k => !hidden.has(k)).map(dashCard).filter(Boolean);
  return `<div class="dash"><div class="dashhead"><h2>${esc(greet)}</h2><span class="muted">${esc(fmtDateLoc(today()))}</span><span class="spacer"></span><button type="button" class="btn sm" data-act="dash-custom">${ic('sliders', 's')}${tr('Customize')}</button></div>
    <div class="dgrid">${cards.join('') || `<p class="muted">${tr('Every card is hidden. Customize brings them back.')}</p>`}</div></div>`;
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="dash-"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const {order, hidden} = dashPref();
  if (a.dataset.act === 'dash-custom') { S.dash.custom = true; renderView(); setTimeout(() => $('#view .dcust button:not([disabled])')?.focus(), 0); }
  else if (a.dataset.act === 'dash-done') { S.dash.custom = false; renderView(); setTimeout(() => { if (document) $('#view [data-act="dash-custom"]')?.focus(); }, 0); }
  else if (a.dataset.act === 'dash-reset') dashSave(DASH.map(d => d[0]), new Set());
  else if (a.dataset.act === 'dash-mv') {
    const i = order.indexOf(a.dataset.k), j = i + +a.dataset.d; if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]]; dashSave(order, hidden);
    announce(+a.dataset.d < 0 ? tr('Moved up') : tr('Moved down'));
    setTimeout(() => $(`#view .dcust [data-act="dash-mv"][data-k="${a.dataset.k}"][data-d="${a.dataset.d}"]:not([disabled])`)?.focus() || $(`#view .dcust [data-act="dash-mv"][data-k="${a.dataset.k}"]:not([disabled])`)?.focus(), 30);
  }
});
document.addEventListener('change', e => {
  const k = e.target.dataset?.dshow; if (!k) return;
  const {order, hidden} = dashPref(); if (e.target.checked) hidden.delete(k); else hidden.add(k);
  dashSave(order, hidden); setTimeout(() => $(`#view [data-dshow="${k}"]`)?.focus(), 30);
});
document.addEventListener('submit', e => {
  if (!e.target.matches?.('[data-dsearch]')) return;
  e.preventDefault();
  const q = $('#dash-q')?.value.trim() || '';
  openPalette(); const inp = $('.palette .pqin'); if (inp && q) { inp.value = q; PAL.q = q; palDraw(); }
});

// ------------------------------------------------------------------ #443 Settings: tasks by e-mail
const mchk = (id, on, label) => `<label class="chkl"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${esc(label)}</label>`;
function mailHtml(j) {
  if (!j) return `<div class="muted">${tr('Loading…')}</div>`;
  const row = (lab, addr, lid) => `<div class="row mailrow"><label>${esc(lab)}</label>${addr ? `<code class="topic mailaddr">${esc(addr)}</code><button type="button" class="btn sm" data-mail="copy" data-addr="${esc(addr)}">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm" data-mail="new" data-lid="${lid ?? ''}">${ic('sync', 's')} ${tr('New address')}</button><button type="button" class="iconbtn" data-mail="del" data-lid="${lid ?? ''}" aria-label="${esc(tr('Remove') + ': ' + addr)}">${ic('x', 's')}</button>`
    : `<button type="button" class="btn sm pri" data-mail="new" data-lid="${lid ?? ''}">${ic('plus', 's')} ${tr('Create an address')}</button>`}</div>`;
  const own = S.lists.filter(l => !l.archived && !l.is_inbox && canEditList(l.id) && !j.lists.some(x => x.list_id === l.id));
  return j.enabled ? `${row(tr('Your inbox'), j.address)}
    ${j.lists.map(x => row(x.name, x.address, x.list_id)).join('')}
    ${own.length ? `<div class="row"><label for="mail-list">${tr('For a list')}</label><select id="mail-list" data-native>${own.map(l => `<option value="${l.id}">${esc(lname(l))}</option>`).join('')}</select><button type="button" class="btn sm" data-mail="newlist">${ic('plus', 's')} ${tr('Create')}</button></div>` : ''}
    <div class="shint">${tr('Subject = title, the text = description, attachments become files. Keep the address secret: whoever knows it can add tasks.')}</div>
    <div class="row"><label></label>${mchk('s-mailme', j.from_me, tr('Mails from my own address ({0}) to {1} go to my inbox', j.email || tr('none set'), j.plain))}</div>`
    : `<div class="shint">${tr('Not set up on this server: an admin sets KALMIDO_MAIL_ADDRESS and KALMIDO_IMAP_* (see the README).')}</div>`;
}
function mailDigestHtml(j) {
  if (!j) return '';
  return `<div class="row"><span class="rlab">${tr('Summary by e-mail')}</span>${j.digest.enabled ? mchk('s-digmail', j.digest.on, tr('Also send the daily summary by e-mail (at the time above, to {0})', j.email || tr('your e-mail address'))) : `<span class="muted">${tr('E-mail sending is not set up on this server')}</span>`}${j.digest.enabled && j.email ? `<button type="button" class="btn sm" data-mail="test">${ic('send', 's')} ${tr('Send now')}</button>` : ''}</div>`;
}
async function mailWire(md) {
  const box = $('#s-mail', md), dbx = $('#s-digmail-w', md); if (!box && !dbx) return;
  let j = null;
  const draw = () => { if (box) box.innerHTML = mailHtml(j); if (dbx) dbx.innerHTML = mailDigestHtml(j); };
  const reload = async () => { try { j = await api('GET', '/api/me/mail'); } catch { return; } draw(); };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-mail]'); if (!b) return;
    const k = b.dataset.mail, lid = b.dataset.lid ? +b.dataset.lid : null;
    if (k === 'copy') { navigator.clipboard?.writeText(b.dataset.addr).then(() => toast(tr('Copied'))); return; }
    if (k === 'new' || k === 'newlist') {
      if (k === 'new' && (lid ? j.lists.some(x => x.list_id === lid) : j.address) && !await askConfirm(tr('A new address?'), tr('The old one stops working at once.'), {ok: tr('New address')})) return;
      try { await api('POST', '/api/me/mail/token', {list_id: k === 'newlist' ? +$('#mail-list', md).value : lid}); } catch { return; }
      await reload(); announce(tr('New address created')); return;
    }
    if (k === 'del') { if (!await askConfirm(tr('Remove this address?'), tr('Mails to it are no longer imported.'), {ok: tr('Remove'), danger: true})) return; try { await api('DELETE', '/api/me/mail/token' + (lid ? `?list_id=${lid}` : '')); } catch { return; } await reload(); return; }
    if (k === 'test') { try { const r = await api('POST', '/api/me/mail/test'); toast(tr('Sent to {0}', r.to)); } catch { /* api() said it */ } }
  });
  md.addEventListener('change', async e => {
    if (e.target.id === 's-mailme') { await api('PATCH', '/api/settings', {mail_from_me: e.target.checked ? '1' : '0'}).catch(() => {}); S.settings.mail_from_me = e.target.checked ? '1' : '0'; }
    if (e.target.id === 's-digmail') { await api('PATCH', '/api/settings', {digest_mail: e.target.checked ? '1' : '0'}).catch(() => {}); S.settings.digest_mail = e.target.checked ? '1' : '0'; }
  });
  reload();
}
