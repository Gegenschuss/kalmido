/* Kalmido web client: several Kalmido servers in one app, the merged view (2.73.0, #661 part C).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.73.0 C (#661): the accounts on other Kalmido servers (Settings > Account > Servers, servers.js) shown next to the
// own data: a sidebar group per server, their tasks in Today and the Basket, search, News, the calendar, the quick add
// target and "Move to another server". The browser only talks to its own server (/api/servers…, it reaches the other
// server with the stored token); nothing is synced. Their data lives in S.msvv, NEVER in S.tasks (ids are per server;
// undo, the offline outbox and the live updates hang on S.tasks); foreign rows carry data-msv="<sid>:<id>".
// Without a linked server nothing changes: one GET /api/servers at the start (a 404 before part A is taken quietly).
const MSVV_POLL = 60e3, MSVV_NEWS = 300e3;
const MSVV_ERR = {offline: N_('not reachable'), auth: N_('sign-in no longer valid'), denied: N_('no access'), notfound: N_('not found'),
  rate: N_('too many requests, please wait a moment'), busy: N_('too many requests, please wait a moment'), version: N_('needs a newer Kalmido version'), invalid: N_('unexpected answer')};
const msvvErrText = code => tr(MSVV_ERR[code] || MSVV_ERR.offline);
const msvvOn = () => !!S.msvv.links.length;
const msvvLink = sid => S.msvv.links.find(l => l.id === +sid) || null;
const msvvName = sid => +sid ? msvvLink(sid)?.name || '?' : S.msvv.self?.name || tr('This server');
const msvvArr = a => Array.isArray(a) ? a : [];
const msvvPrio = p => [1, 3, 5].includes(+p) ? +p : 0;
const msvvUrl = u => typeof u === 'string' && /^https?:\/\//i.test(u) ? u : '';
const msvvTime = at => { const d = at ? new Date(at) : null; return d && !isNaN(d) ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : ''; };

// the own small caller: no offline exit, no outbox, no login screen (a foreign write is never queued; a failure is said)
async function msvvFetch(method, url, body) {
  const opt = {method, headers: {'X-Requested-With': 'kalmido'}, redirect: 'manual', credentials: 'same-origin'};
  if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  let r;
  try { r = await fetch(url, opt); } catch { const e = new Error(msvvErrText('offline')); e.code = 'offline'; throw e; }
  const j = await r.json().catch(() => null);
  if (!r.ok || !j || typeof j !== 'object') {
    const e = new Error(j?.error || httpErrText(r.status)); e.status = r.status;
    e.code = j?.code || (r.status === 404 ? 'notfound' : r.status === 429 ? 'rate' : 'offline'); throw e;
  }
  return j;
}
// a failed foreign write: one quiet toast that names the server
// (a 424 carries the other server's reason as translated plain text, part A)
const msvvFail = (sid, e) => toast(tr('{0}: {1}', msvvName(sid), e?.message || msvvErrText(e?.code)), null, 5000);

// ---- state
async function msvvLoad() {
  if (S.msvv.busy) return; S.msvv.busy = true;
  try {
    let j = S.msvv.pre; S.msvv.pre = null;  // 2.149.0 F (#2518): the answer of the start's probe (render.js), once
    if (!j) try { j = await msvvFetch('GET', '/api/servers'); } catch { S.msvv.loaded = true; return; }  // 404 before part A, offline: as it is
    const had = msvvOn();
    S.msvv.self = j.self && typeof j.self === 'object' ? j.self : null;
    S.msvv.links = msvvArr(j.links).filter(l => l && +l.id > 0).map(l => ({...l, id: +l.id}))
      .sort((a, b) => (+a.position || 0) - (+b.position || 0) || a.id - b.id);
    S.msvv.loaded = true; S.msvv.at = Date.now();
    for (const k of Object.keys(S.msvv.data)) if (!msvvLink(k)) delete S.msvv.data[k];
    if (!msvvOn()) { if (had || S.route.mod === 'msv') { S.msvv.sig = ''; msvvDraw(); } return; }  // 2.149.0 F (#2518): + a list of a server that is not linked, opened before the module was there
    // 2.73.0 A (#661) review H1: at most three at once (the server answers "busy" at once instead of waiting for a slot)
    const q = S.msvv.links.map(l => l.id);
    await Promise.all([0, 1, 2].map(async () => { while (q.length) await msvvData(q.shift()); }));
    if (Date.now() - (S.msvv.newsAt || 0) > MSVV_NEWS || S.route.mod === 'news') msvvNewsLoad();
    // the poll redraws only when something changed (the answer's time aside)
    const sig = JSON.stringify([S.msvv.self, S.msvv.links.map(({at, ...l}) => l), S.msvv.links.map(l => { const d = S.msvv.data[l.id] || {}; return [d.lists, d.tasks, d.today, d.err]; })]);
    if (sig !== S.msvv.sig) { S.msvv.sig = sig; msvvDraw(); }
  } finally { S.msvv.busy = false; }
}
async function msvvData(sid, again) {
  const d0 = S.msvv.data[sid] || {lists: [], tasks: [], today: '', at: '', err: null};
  try {
    const j = await msvvFetch('GET', `/api/servers/${sid}/data`);
    S.msvv.data[sid] = {lists: msvvArr(j.lists).map(l => ({...l, id: +l.id})), tasks: msvvArr(j.tasks).map(t => ({...t, id: +t.id, list_id: +t.list_id, parent_id: +t.parent_id || null, priority: msvvPrio(t.priority), status: +t.status || 0, tags: msvvArr(t.tags)})),
      today: /^\d{4}-\d{2}-\d{2}$/.test(j.today || '') ? j.today : today(), at: j.at || new Date().toISOString(), err: null};
  } catch (e) {
    // review H1: "busy" = this server has no free slot right now: once more after a moment, then the last state stays quietly
    if (e.code === 'busy') { if (!again) { await new Promise(r => setTimeout(r, 1500 + Math.random() * 1000)); return msvvData(sid, true); } S.msvv.data[sid] = d0; return; }
    S.msvv.data[sid] = {...d0, err: e.code || 'offline'};
  }
}
// what a change of S.msvv redraws: the sidebar, and the view when it shows foreign data
function msvvDraw() {
  if (!S.booted) return;
  renderSide();
  const r = S.route;
  if (r.mod === 'msv' || r.mod === 'news' || r.mod === 'cal' || (r.mod === 'tasks' && ['today', 'inbox'].includes(r.key))) { renderTop(); viewSafeRender(); }
  if (r.mod === 'tasks') qdockChips();
}
function msvvBoot() {
  if (msvvBoot.done || S.me?.kid) return; msvvBoot.done = true;
  msvvLoad();
  setInterval(() => { if (msvvOn() && !document.hidden) msvvLoad(); }, MSVV_POLL);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && msvvOn() && Date.now() - S.msvv.at > 20e3) msvvLoad(); });
  document.addEventListener('msv:changed', () => msvvLoad());  // servers.js: an account was added, changed or removed
}
const msvvTask = (sid, id) => S.msvv.data[sid]?.tasks.find(t => t.id === +id) || S.msvv.data[sid]?.extra?.[+id] || null;
const msvvList = (sid, lid) => S.msvv.data[sid]?.lists.find(l => l.id === +lid) || null;
const msvvCanWrite = (sid, lid) => !!msvvList(sid, lid)?.can_write;
const msvvKids = (sid, id) => (S.msvv.data[sid]?.tasks || []).filter(t => t.parent_id === id && t.status === 0);
function msvvPut(sid, t) {  // an answer of a write replaces the task in S.msvv (an open one) or drops it (done / deleted)
  const d = S.msvv.data[sid]; if (!d || !t || !(+t.id > 0)) return;
  const n = {...t, id: +t.id, list_id: +t.list_id, parent_id: +t.parent_id || null, priority: msvvPrio(t.priority), status: +t.status || 0, tags: msvvArr(t.tags)};
  const i = d.tasks.findIndex(x => x.id === n.id);
  if (i >= 0) d.tasks[i] = {...d.tasks[i], ...n}; else d.tasks.push(n);
}

// ---- the badge: the server's short name in its colour (muted), its name for screen readers and as tooltip
function msvvBadge(sid, cls = '') {
  const l = +sid ? msvvLink(sid) : S.msvv.self || {};
  if (!l) return '';
  const nm = msvvName(sid), sh = String(l.short || initials(nm)).slice(0, 3), c = cssColor(l.color);
  return `<span class="msvb ${cls}"${c ? ` style="--msvc:${c}"` : ''} role="img" aria-label="${esc(tr('Server: {0}', nm))}" title="${esc(nm)}">${esc(sh)}</span>`;
}
// own rows in the merged views (Today, Basket, Search) carry the own badge once a server is linked; normal lists do not
function msvvSelfBadge(opts = {}) {
  if (!msvvOn() || opts.depth || opts.subRow || opts.trash || S.route.mod !== 'tasks' || !['today', 'inbox', 'search'].includes(S.route.key)) return '';
  return msvvBadge(0);
}
const msvvErrLine = sid => {
  const d = S.msvv.data[sid]; if (!d?.err) return '';
  const tm = msvvTime(d.at);
  return `<div class="msvverr" role="status">${ic('cloudoff', 's')}<span>${esc(tm ? tr('{0} {1} – last update {2}', msvvName(sid), msvvErrText(d.err), tm) : tr('{0} {1}', msvvName(sid), msvvErrText(d.err)))}</span></div>`;
};

// ---- a foreign task row (the classes of taskRow, its own data-msv instead of data-id: the own handlers leave it alone)
function msvvRow(sid, t, o = {}) {
  const d = S.msvv.data[sid], ro = !msvvCanWrite(sid, t.list_id), meta = [msvvBadge(sid)];
  const lst = o.showList ? msvvList(sid, t.list_id)?.name || '' : '';
  if (lst) meta.push(`<span class="lst" title="${esc(lst)}">${esc(lst)}</span>`);
  if (t.due) { const ov = !t.status && t.due < (d?.today || today()); meta.push(`<span class="dt ${ov ? 'over' : t.due === (d?.today || today()) && !t.status ? 'today' : ''}">${ov ? ic('alert', 's') + `<span class="sr">${tr('Overdue')}: </span>` : ic('cal', 's')}${esc(dueLabel(t, false))}</span>`); }
  const kids = o.depth ? [] : msvvKids(sid, t.id);
  for (const g of msvvArr(t.tags).slice(0, 4)) meta.push(`<span class="tag">#${esc(g)}</span>`);
  const p = msvvPrio(t.priority), chk = t.status === 2 ? 'on' : 'p' + p;
  const title = String(t.title || '');
  const h = `<div class="trow msvrow ${p ? 'pr' + p : ''} ${t.status ? 'done' : ''} ${o.depth ? 'sub d1' : ''} ${ro ? 'ro' : ''}" data-msv="${+sid}:${+t.id}">
    <button class="chk ${chk}" data-msvv="toggle" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(tr('Complete: {0}', title))}" ${ro ? 'disabled' : ''}>${t.status === 2 ? ic('check') : ''}</button>
    <div class="tmain" data-msvv="open"><div class="ttl" role="button" tabindex="0">${esc(title)}${p && !t.status ? prioMark(p) : ''}</div><div class="meta">${meta.join('')}</div></div></div>`;
  return h + (o.tree === false ? '' : kids.map(k => msvvRow(sid, k, {depth: 1})).join(''));
}
const msvvRowKey = (a, b) => (a.due || '9999').localeCompare(b.due || '9999') || msvvPrio(b.priority) - msvvPrio(a.priority);
// the roots of a set of foreign tasks (a subtask whose parent is in the set shows below it)
const msvvRoots = ts => { const ids = new Set(ts.map(t => t.id)); return ts.filter(t => !t.parent_id || !ids.has(t.parent_id)); };

// ---- Today + Basket: the foreign tasks by the same rules (Today: due on or before the server's today; Basket: its inbox list)
function msvvViewTasks(k) {
  const out = [];
  for (const l of S.msvv.links) {
    const d = S.msvv.data[l.id]; if (!d) continue;
    const inb = new Set(d.lists.filter(x => x.inbox).map(x => x.id));
    const m = d.tasks.filter(t => t.status === 0 && (k === 'today' ? t.due && t.due <= d.today : inb.has(t.list_id)));
    for (const t of msvvRoots(m)) out.push({id: `m${l.id}:${t.id}`, due: t.due, priority: t.priority, status: 0, list_id: 0, title: t.title, tags: [], _msv: {sid: l.id, t, today: d.today}});
  }
  return out;
}
// groupTasks() of Today / the Basket plus the foreign tasks, sorted in by date and priority like the own ones (render.js viewListBody)
function msvvMerge(groups, v) {
  const k = S.route.key;
  if (!msvvOn() || S.route.mod !== 'tasks' || (k !== 'today' && k !== 'inbox')) return groups;
  const add = msvvViewTasks(k); if (!add.length) return groups;
  const gs = groups.map(g => ({...g, tasks: g.tasks.slice()})), dated = k === 'today' && gs.some(g => /^d:/.test(String(g.id)));
  for (const f of add) {
    let g;
    if (dated) {
      const id = f.due < f._msv.today ? 'd:over' : 'd:' + today();
      g = gs.find(x => x.id === id);
      if (!g) { g = {id, name: id === 'd:over' ? tr('Overdue') : dayLabel(today(), true), cls: id === 'd:over' ? 'over' : '', tasks: []}; const at = id === 'd:over' ? gs.findIndex(x => x.id !== 'pinned') : gs.findIndex(x => /^d:/.test(String(x.id)) && x.id !== 'd:over'); gs.splice(at < 0 ? gs.length : at, 0, g); }
    } else g = gs.find(x => x.id !== 'pinned' && !x.folded) || (gs.push({id: 'all', name: '', tasks: []}), gs[gs.length - 1]);
    const i = g.tasks.findIndex(t => !t.pinned && msvvRowKey(f, t) < 0);
    g.tasks.splice(i < 0 ? g.tasks.length : i, 0, f);
  }
  return gs;
}
// the sidebar numbers of Today / the Basket with the foreign open tasks
function msvvCount(n, k) {
  if (!msvvOn() || (k !== 'today' && k !== 'inbox')) return n;
  const add = msvvViewTasks(k).length;
  return add ? (+n || 0) + add : n;
}

// ---- the sidebar: one foldable group per server (badge + name, a quiet error line) with its lists
function msvvSide() {
  if (!msvvOn()) return '';
  return S.msvv.links.map(l => {
    const d = S.msvv.data[l.id] || {lists: [], tasks: []}, key = 'msvside:' + l.id, closed = S.collapsed.has(key);
    const on = S.route.mod === 'msv' && S.route.sid === l.id;
    const cnt = lid => d.tasks.filter(t => t.list_id === lid && t.status === 0 && !t.parent_id).length;
    const rows = d.lists.map(x => `<button class="srow msvsrow ${on && S.route.lid === x.id ? 'on' : ''}" data-go="srv/${l.id}/${x.id}"><span class="sic" aria-hidden="true">${ic(x.inbox ? 'inbox' : 'list', 's')}</span><span class="n">${esc(x.name || '')}</span><span class="c">${cnt(x.id) || ''}</span></button>`).join('');
    return `<div class="sgroup sg-msv" data-msvside="${l.id}"><div class="shead sgh ${closed ? 'closed' : ''} ${on && closed ? 'sgon' : ''}"><button class="sgt" data-msvv-fold="${l.id}" aria-expanded="${!closed}">${ic('chev', 's fcar')}${msvvBadge(l.id)}<span>${esc(l.name || '?')}</span>${d.err ? `<span class="msvvoff" title="${esc(msvvErrText(d.err))}">${ic('cloudoff', 's')}<span class="sr">${esc(msvvErrText(d.err))}</span></span>` : ''}</button><span class="spacer"></span></div>${closed ? '' : (d.err ? msvvErrLine(l.id) : '') + (rows || `<div class="fempty">${esc(d.err ? '' : S.msvv.data[l.id] ? tr('No projects') : tr('Loading…'))}</div>`)}</div>`;
  }).join('');
}

// ---- a foreign list (#srv/<sid>/<lid>): its open tasks, ticking off, a quick add into it
function msvvTitle() { const {sid, lid} = S.route; return msvvList(sid, lid)?.name || msvvName(sid); }
function msvvViewList() {
  const {sid, lid} = S.route, l = msvvLink(sid), d = S.msvv.data[sid];
  if (!l) return botEmpty('ruhig', S.msvv.loaded ? tr('This server is not connected (any more).') : tr('Loading…'));
  const lst = msvvList(sid, lid);
  const ts = d ? msvvRoots(d.tasks.filter(t => t.list_id === lid && t.status === 0)).sort(msvvRowKey) : [];
  const head = `<div class="msvvhead">${msvvBadge(sid)}<span>${esc(l.name || '')}${lst ? ' · ' + esc(lst.name || '') : ''}</span>${l.base_url && msvvUrl(l.base_url) ? `<a class="btn sm" href="${esc(msvvUrl(l.base_url))}" target="_blank" rel="noopener noreferrer">${ic('link', 's')}${esc(tr('Open on {0}', l.name || '?'))}</a>` : ''}</div>`;
  const add = lst?.can_write ? `<div class="qadd dock msvvqa"><div class="box"><span class="qplus" aria-hidden="true">${ic('plus', 's')}</span><input id="msvv-in" type="text" autocomplete="off" enterkeyhint="done" data-form-type="other" data-lpignore="true" aria-label="${esc(tr('Add a task to {0} on {1}', lst.name || '', l.name || ''))}" placeholder="${esc(tr('Add task…'))}"></div></div>` : '';
  const body = !d ? `<div class="empty">${tr('Loading…')}</div>` : !lst ? botEmpty('ruhig', tr('This project does not exist or you cannot see it.'))
    : ts.length ? ts.map(t => msvvRow(sid, t)).join('') : symEmpty('list', tr('No tasks.'));
  return `<div class="lwrap msvvlist">${head}${msvvErrLine(sid)}${add}${body}</div>`;
}

// ---- writes on a foreign task
async function msvvToggle(sid, id) {
  const t = msvvTask(sid, id); if (!t) return;
  if (!msvvCanWrite(sid, t.list_id)) { toast(tr('View only')); return; }
  const done = t.status === 2;
  try {
    const n = await msvvFetch('POST', `/api/servers/${sid}/tasks/${id}/${done ? 'reopen' : 'complete'}`);
    msvvPut(sid, n?.id ? n : {...t, status: done ? 0 : 2}); msvvDraw();
    // the undo is a toast of its own (the own undo history works on S.tasks)
    if (!done) toast(tr('Completed: {0}', String(t.title || '')), async () => { try { msvvPut(sid, await msvvFetch('POST', `/api/servers/${sid}/tasks/${id}/reopen`)); msvvDraw(); } catch (e) { msvvFail(sid, e); } }, 5000);
    msvvData(sid).then(msvvDraw);
  } catch (e) { msvvFail(sid, e); }
}
async function msvvAdd(sid, lid, body) {
  try {
    const n = await msvvFetch('POST', `/api/servers/${sid}/tasks`, {...(lid ? {list_id: lid} : {}), ...body});
    if (n?.id) msvvPut(sid, n);
    msvvDraw(); msvvData(sid).then(msvvDraw);
    return n || {};
  } catch (e) { msvvFail(sid, e); return null; }
}
// the quick add words: the title, the date and the priority; the rest stays in the title
function msvvParse(txt) {
  const r = parseQuick(txt, S.quick.ignore);
  let title = r.title || txt;
  if (r.tags?.length) title += ' ' + r.tags.map(g => '#' + g).join(' ');
  return {title: title.trim(), ...(r.due ? {due: r.due} : {}), ...(r.priority ? {priority: r.priority} : {}), _r: r};
}

// ---- the details of a foreign task: a small panel of its own (title, notes, date, priority, subtasks, done, trash, open there)
async function msvvOpen(sid, id) {
  const l = msvvLink(sid); if (!l) return;
  const t0 = msvvTask(sid, id);
  const md = modal(`<div class="lhdr msvvdh">${msvvBadge(sid)}<span class="msvvdsrv">${esc(l.name || '')}<span class="muted" id="msvvd-l">${t0 && msvvList(sid, t0.list_id) ? ' · ' + esc(msvvList(sid, t0.list_id).name || '') : ''}</span></span><span class="spacer"></span><button class="iconbtn" data-msvd="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div><div id="msvvd-b"><div class="muted">${tr('Loading…')}</div></div>`);
  md.classList.add('msvvdlg'); md.dataset.msv = `${sid}:${id}`;
  md.addEventListener('click', e => { if (e.target.closest('[data-msvd="close"]')) md.remove(); });
  let t;
  try { t = await msvvFetch('GET', `/api/servers/${sid}/tasks/${id}`); }
  catch (e) { if (md.isConnected) $('#msvvd-b', md).innerHTML = `<div class="msvverr" role="status">${ic('cloudoff', 's')}<span>${esc(tr('{0}: {1}', l.name || '?', msvvErrText(e.code)))}</span></div>`; return; }
  if (!md.isConnected) return;
  msvvDetailDraw(md, sid, t);
}
function msvvDetailDraw(md, sid, t) {
  const l = msvvLink(sid), lst = msvvList(sid, t.list_id), ro = !(lst ? lst.can_write : msvvCanWrite(sid, t.list_id)), p = msvvPrio(t.priority), url = msvvUrl(t.url);
  const nc = +t.comments_count || 0, na = +t.attachments_count || 0, done = +t.status === 2;
  $('#msvvd-l', md).textContent = lst ? ' · ' + (lst.name || '') : '';
  $('#msvvd-b', md).innerHTML = `<form class="msvvdf" novalidate>
    <label class="sr" for="msvvd-t">${esc(tr('Title'))}</label><input id="msvvd-t" class="msvvdt" value="${esc(t.title || '')}" maxlength="500" ${ro ? 'readonly' : ''}>
    <div class="msvvdrow"><label>${ic('cal', 's')}<span>${esc(tr('Date'))}</span>${dateIn('msvvd-due', /^\d{4}-\d{2}-\d{2}$/.test(t.due || '') ? t.due : '', {ro, label: tr('Date')})}</label>
      <label>${ic('flag', 's')}<span>${esc(tr('Priority'))}</span><select id="msvvd-p" ${ro ? 'disabled' : ''}>${[[0, N_('None')], [1, N_('Low')], [3, N_('Medium')], [5, N_('High')]].map(([v, n]) => `<option value="${v}" ${v === p ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select></label></div>
    <label class="sr" for="msvvd-n">${esc(tr('Notes'))}</label><textarea id="msvvd-n" rows="5" placeholder="${esc(tr('Notes'))}" ${ro ? 'readonly' : ''}>${esc(t.notes || '')}</textarea>
    ${msvvArr(t.subtasks).length ? `<h4>${esc(tr('Subtasks'))}</h4><ul class="msvvsubs">${msvvArr(t.subtasks).map(s => `<li class="${+s.status ? 'done' : ''}">${ic(+s.status === 2 ? 'check' : 'sub', 's')}<span>${esc(s.title || '')}</span></li>`).join('')}</ul>` : ''}
    ${nc || na ? `<p class="muted msvvcnt">${esc([nc ? trn('{0} comment', '{0} comments', nc) : '', na ? trn('{0} attachment', '{0} attachments', na) : ''].filter(Boolean).join(' · '))} – ${esc(tr('open on {0}', l?.name || '?'))}</p>` : ''}
    <div class="foot msvvfoot">
      ${ro ? '' : `<button type="button" class="btn" data-msvd="toggle">${ic(done ? 'undo' : 'check', 's')}${esc(done ? tr('Reopen') : tr('Complete'))}</button>`}
      ${url ? `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${ic('link', 's')}${esc(tr('Open on {0}', l?.name || '?'))}</a>` : ''}
      ${ro ? '' : `<button type="button" class="btn" data-msvd="move">${ic('arrow', 's')}${esc(tr('Move to another server…'))}</button><button type="button" class="btn danger" data-msvd="delete">${ic('trash', 's')}${esc(tr('Delete'))}</button>`}
      <span class="spacer"></span>${ro ? '' : `<button type="submit" class="btn pri" data-msvd="save">${esc(tr('Save'))}</button>`}</div></form>`;
  const f = $('form', md);
  f.addEventListener('submit', async e => {
    e.preventDefault(); if (ro) return;
    const b = {}, ti = $('#msvvd-t', md).value.trim(), du = $('#msvvd-due', md).value || null, pr = +$('#msvvd-p', md).value, no = $('#msvvd-n', md).value;
    if (ti && ti !== (t.title || '')) b.title = ti;
    if (du !== (t.due || null)) b.due = du;
    if (pr !== p) b.priority = pr;
    if (no !== (t.notes || '')) b.notes = no;
    if (!Object.keys(b).length) { md.remove(); return; }
    try { const n = await msvvFetch('PATCH', `/api/servers/${sid}/tasks/${t.id}`, b); msvvPut(sid, n?.id ? n : {...t, ...b}); msvvDraw(); md.remove(); toast(tr('Saved on {0}', l?.name || '?')); }
    catch (er) { msvvFail(sid, er); }
  });
  f.addEventListener('click', async e => {
    const a = e.target.closest('[data-msvd]'); if (!a || a.dataset.msvd === 'save') return;
    if (a.dataset.msvd === 'toggle') { md.remove(); await msvvToggle(sid, t.id); }
    else if (a.dataset.msvd === 'move') msvvMoveDlg({server: sid, task: t.id, title: t.title || ''}, md);
    else if (a.dataset.msvd === 'delete') {
      if (!await askConfirm(tr('Delete on {0}?', l?.name || '?'), tr('“{0}” goes to the trash on {1} and can be restored there.', t.title || '', l?.name || '?'), {ok: tr('Delete'), danger: true})) return;
      try { await msvvFetch('DELETE', `/api/servers/${sid}/tasks/${t.id}`); const d = S.msvv.data[sid]; if (d) d.tasks = d.tasks.filter(x => x.id !== t.id); md.remove(); msvvDraw(); toast(tr('Moved to the trash on {0}', l?.name || '?')); }
      catch (er) { msvvFail(sid, er); }
    }
  });
}

// ---- move a task to another server (own or foreign): pick server + list, a plain question, POST /api/servers/move
function msvvMoveItem(t) {
  if (!msvvOn() || !t || !(t.id > 0) || t.context || !canEdit(t)) return [];
  return [{label: tr('Move to another server…'), icon: 'arrow', fn: () => msvvMoveDlg({server: 0, task: t.id, title: t.title || '', lid: t.list_id})}];
}
const msvvTargets = from => [...(from ? [0] : []), ...S.msvv.links.map(l => l.id).filter(id => id !== from)];
function msvvTargetLists(sid) {
  if (!+sid) return [inbox(), ...S.lists.filter(l => !l.is_inbox && !l.archived && canAddTo(l.id))].filter(Boolean).map(l => ({id: l.id, name: l.is_inbox ? tr('Basket') : lname(l), inbox: !!l.is_inbox}));
  return (S.msvv.data[sid]?.lists || []).filter(l => l.can_write).map(l => ({id: l.id, name: l.name || '', inbox: !!l.inbox}));
}
function msvvMoveDlg(src, parent) {
  const tg = msvvTargets(src.server); if (!tg.length) return;
  let to = tg[0];
  const opts = () => msvvTargetLists(to).map(l => `<option value="${l.id}" ${l.inbox ? 'selected' : ''}>${esc(l.name)}</option>`).join('');
  const md = modal(`<form class="msvvmv" novalidate><h3 id="msvvmv-h">${esc(tr('Move to another server'))}</h3><p class="muted">${esc(tr('“{0}”|quoted', src.title.length > 60 ? src.title.slice(0, 59) + '…' : src.title))}</p>
    <label class="flbl" for="msvvmv-s">${esc(tr('Server'))}</label><select id="msvvmv-s">${tg.map(id => `<option value="${id}">${esc(msvvName(id))}</option>`).join('')}</select>
    <label class="flbl" for="msvvmv-l">${esc(tr('Project'))}</label><select id="msvvmv-l">${opts()}</select>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-msvm="no">${esc(tr('Cancel'))}</button><button type="submit" class="btn pri">${esc(tr('Continue'))}</button></div></form>`);
  md.classList.add('msvvmvdlg');
  const fixList = () => { const s = $('#msvvmv-l', md); s.innerHTML = opts(); s.disabled = !s.options.length; };
  fixList();
  $('#msvvmv-s', md).addEventListener('change', e => { to = +e.target.value; fixList(); });
  md.addEventListener('click', e => { if (e.target.closest('[data-msvm="no"]')) md.remove(); });
  $('form', md).addEventListener('submit', async e => {
    e.preventDefault();
    const lid = +$('#msvvmv-l', md).value || null, srcN = msvvName(src.server), dstN = msvvName(to);
    if (!msvvTargetLists(to).length) { toast(tr('No project on {0} that you can add to', dstN)); return; }
    md.remove();
    // 2.73.0 A (#661) review question 1: a task of an organisation's list says that it leaves the organisation (no lock: the product owner decides)
    const org = !src.server && typeof listById === 'function' ? listById(src.lid)?.org_id : null;
    const orgLine = org && typeof wsLabel === 'function' ? ' ' + tr('The task leaves the organisation {0} with it.', wsLabel(org)) : '';
    if (!await askConfirm(tr('Move to {0}?', dstN), tr('It is created anew on {0} (title, notes, date, priority, open subtasks). Comments, attachments and history stay on {1} in the trash.', dstN, srcN) + orgLine, {ok: tr('Move')})) return;
    let j;
    try { j = await msvvFetch('POST', '/api/servers/move', {from: {server: src.server, task: src.task}, to: {server: to, list_id: lid}}); }
    catch (er) { msvvFail(to || src.server, er); return; }
    if (parent?.isConnected) parent.remove();
    if (!src.server && S.sel === src.task && typeof closeDetail === 'function') closeDetail();
    const lost = j.lost || {}, nl = (+lost.comments || 0) + (+lost.attachments || 0);
    const ls = +lost.subtasks || 0;  // review N3: subtasks the other server did not take
    toast([tr('Moved to {0}', dstN), ls ? trn('{0} subtask could not be created on {1}.', '{0} subtasks could not be created on {1}.', ls, dstN) : '', j.source_kept ? tr('The original stays on {0}: it could not be moved to the trash.', srcN) : nl ? tr('Comments and attachments stay on {0} in the trash.', srcN) : ''].filter(Boolean).join(' · '), null, 6000);
    if (!src.server || !to) refreshNow().catch(() => {});
    await Promise.all([src.server, to].filter(Boolean).map(id => msvvData(id))); msvvDraw();
  });
}

// ---- the quick add target ("→ Server · List"): the open foreign list, else the server set as default basket, else this one
const msvvQKey = () => S.route.mod === 'msv' ? `srv/${S.route.sid}/${S.route.lid}` : S.route.key;
function msvvQDefault() {
  const r = S.route;
  if (r.mod === 'msv' && msvvLink(r.sid)) return {sid: r.sid, lid: r.lid};
  if (r.mod === 'tasks' && (r.key === 'inbox' || r.key.startsWith('l:') || r.key.startsWith('folder:'))) return {sid: 0};
  const dl = S.msvv.links.find(l => l.default_inbox); return dl ? {sid: dl.id, lid: null} : {sid: 0};
}
const msvvQT = () => S.msvvQ && S.msvvQ.key === msvvQKey() && (!S.msvvQ.sid || msvvLink(S.msvvQ.sid)) ? S.msvvQ : msvvQDefault();
const msvvQLabel = q => { const nm = msvvName(q.sid); if (!q.sid) return nm; const lst = q.lid ? msvvList(q.sid, q.lid) : (S.msvv.data[q.sid]?.lists || []).find(l => l.inbox); return nm + ' · ' + (lst?.name || tr('Basket')); };
const msvvQChip = () => { if (!msvvOn()) return ''; const q = msvvQT(); return `<button type="button" class="qdc set msvvqc ${q.sid ? 'far' : ''}" data-msvvq="1" aria-haspopup="menu" title="${esc(tr('Where the task goes'))}">${msvvBadge(q.sid)}<span>→ ${esc(msvvQLabel(q))}</span></button>`; };
// the docked composer's chips (render.js qdockChips) and the phone sheet (events.js openQuickSheet) show the target
function msvvQSync(box) {
  if (!box) return;
  box.classList.toggle('msvvf', msvvOn() && !!msvvQT().sid);
  $('.msvvqc', box)?.remove();
  const c = msvvQChip(); if (c) box.insertAdjacentHTML('afterbegin', c);
}
function msvvSheetTarget(q) {
  const p = S.quickPreset || {}, own = p.capture || p.list_id || p.files?.length || p.section_id;
  $('.msvvqs', q)?.remove();
  if (!msvvOn() || own) return;
  $('.box', q)?.insertAdjacentHTML('afterend', `<div class="msvvqs qdchips">${msvvQChip()}</div>`);
}
function msvvQPick(a) {
  const key = msvvQKey(), set = (sid, lid) => { S.msvvQ = {key, sid, lid}; msvvQSync($('#qdchips')); const s = $('.qadd.sheet .msvvqs'); if (s) s.innerHTML = msvvQChip(); ($('#qinput') || $('#qsheet'))?.focus(); };
  menu(a, [{label: msvvName(0), icon: 'home', fn: () => set(0, null)}, ...S.msvv.links.map(l => ({label: l.name || '?', icon: 'globe', fn: () => setTimeout(() => {
    const ls = msvvTargetLists(l.id);
    if (!ls.length) { toast(tr('No project on {0} that you can add to', l.name || '?')); return; }
    menu(a, ls.map(x => ({label: x.name, icon: x.inbox ? 'inbox' : 'list', fn: () => set(l.id, x.id)})), null, null, l.name || '');
  }, 0)}))], null, null, tr('Where the task goes'));
}
// submitQuick (events.js): a foreign target takes the task (true = done here); the own target goes on as before
async function msvvQuick(input) {
  if (!msvvOn() || !['qinput', 'qsheet'].includes(input.id)) return false;
  const p = input.id === 'qsheet' ? S.quickPreset || {} : {};
  if (p.capture || p.list_id || p.files?.length || p.section_id || S.qfiles?.[input.id]?.length) return false;
  const q = msvvQT(); if (!q.sid) return false;
  const txt = input.value.trim(); if (!txt) return true;
  const b = msvvParse(txt);
  if (b._r.list_id) return false;  // "~list" names an own list
  delete b._r;
  const o = input.id === 'qinput' && S.qov?.key === S.route.key ? S.qov : {}, d = quickDefaults();
  if (!b.due) b.due = ('due' in o ? o.due : d.due) || undefined;  // 2.380.2 (#3403): the text wins over a chip
  if (b.priority == null && 'priority' in o) b.priority = o.priority;
  if (!b.title) return true;
  input.value = ''; S.quick.ignore = new Set(); updateChips(input);
  const n = await msvvAdd(q.sid, q.lid, JSON.parse(JSON.stringify(b)));
  if (n) toast(tr('Added on {0}', msvvQLabel(q)), null, 4000);
  else input.value = txt;  // not reachable: the text stays
  if (input.id === 'qsheet' && n) closePop();
  return true;
}

// ---- Search: the hits of the other servers below the own ones, one section per server, asked in parallel
function msvvSearch(q) {
  if (!msvvOn()) return;
  const s = S.msvv.search = {q, res: {}};
  if (!q.trim()) { msvvSearchDraw(); return; }
  for (const l of S.msvv.links) {
    s.res[l.id] = null;
    msvvFetch('GET', `/api/servers/${l.id}/search?q=${encodeURIComponent(q)}`)
      .then(j => { s.res[l.id] = {tasks: msvvArr(j.tasks).map(t => ({...t, id: +t.id, list_id: +t.list_id, priority: msvvPrio(t.priority), status: +t.status || 0, tags: msvvArr(t.tags)}))}; },
        e => { s.res[l.id] = {err: e.code || 'offline'}; })
      .then(() => { if (S.msvv.search === s) msvvSearchDraw(); });
  }
  msvvSearchDraw();
}
function msvvSearchHtml() {
  const s = S.msvv.search; if (!msvvOn() || !s.q.trim()) return '';
  return S.msvv.links.map(l => {
    const r = s.res[l.id];
    const body = r === null || r === undefined ? `<div class="muted msvvwait">${tr('Searching…')}</div>` : r.err ? `<div class="msvverr" role="status">${ic('cloudoff', 's')}<span>${esc(tr('{0} {1}', l.name || '?', msvvErrText(r.err)))}</span></div>`
      : r.tasks.length ? r.tasks.map(t => { msvvSeen(l.id, t); return msvvRow(l.id, t, {showList: true, tree: false}); }).join('') : `<div class="muted msvvwait">${tr('No results.')}</div>`;
    return `<div class="group msvvsec"><div class="ghead msvvgh">${msvvBadge(l.id)}<span>${esc(l.name || '?')}</span>${r?.tasks?.length ? `<span class="c">${r.tasks.length}</span>` : ''}</div>${body}</div>`;
  }).join('');
}
function msvvSearchDraw() { const el = $('#msvvsearch'); if (el) el.innerHTML = msvvSearchHtml(); }
// a hit that is not among the open tasks of /data (done, other filters) is kept so its row can open it
function msvvSeen(sid, t) { const d = S.msvv.data[sid]; if (d && !d.tasks.some(x => x.id === t.id)) d.extra = {...(d.extra || {}), [t.id]: t}; }

// ---- News: the unread items of each server as a section of the News view (its number joins the bell's)
async function msvvNewsLoad() {
  if (!msvvOn()) return;
  S.msvv.newsAt = Date.now();
  await Promise.all(S.msvv.links.map(async l => {
    try { const j = await msvvFetch('GET', `/api/servers/${l.id}/news?limit=30`); S.msvv.news[l.id] = {items: msvvArr(j.items), unread: +j.unread || 0, err: null}; }
    catch (e) { S.msvv.news[l.id] = {...(S.msvv.news[l.id] || {items: [], unread: 0}), err: e.code || 'offline'}; }
  }));
  renderSide(); renderTop();
  if (S.route.mod === 'news') viewSafeRender();
}
const msvvUnread = () => msvvOn() ? S.msvv.links.reduce((n, l) => n + (S.msvv.news[l.id]?.unread || 0), 0) : 0;
function msvvNewsHtml() {
  if (!msvvOn()) return '';
  if (Date.now() - (S.msvv.newsAt || 0) > MSVV_POLL) setTimeout(msvvNewsLoad, 0);
  return S.msvv.links.map(l => {
    const n = S.msvv.news[l.id];
    const items = (n?.items || []).filter(it => !S.nf?.unread || !it.read);
    const body = !n ? `<div class="muted msvvwait">${tr('Loading…')}</div>` : n.err && !n.items.length ? `<div class="msvverr" role="status">${ic('cloudoff', 's')}<span>${esc(tr('{0} {1}', l.name || '?', msvvErrText(n.err)))}</span></div>`
      : items.length ? items.map(it => `<button type="button" class="nitem msvvni ${it.read ? 'read' : 'unread'}" data-msvn="${l.id}:${esc(String(it.id))}">${msvvBadge(l.id)}<span class="msvvnt">${esc(String(it.text || ''))}</span><span class="muted">${esc(it.at ? fmtWhen(it.at) : '')}</span></button>`).join('') : `<div class="muted msvvwait">${tr('No news')}</div>`;
    return `<div class="nlist msvvsec"><div class="ghead msvvgh">${msvvBadge(l.id)}<span>${esc(l.name || '?')}</span>${n?.unread ? `<span class="c nunread">${n.unread}</span>` : ''}<span class="spacer"></span>${n?.unread ? `<button type="button" class="btn sm" data-msvnall="${l.id}">${esc(tr('Mark all as read'))}</button>` : ''}</div>${body}</div>`;
  }).join('');
}
async function msvvNewsRead(sid, ids) {
  const n = S.msvv.news[sid]; if (!n || !ids.length) return;
  try { await msvvFetch('POST', `/api/servers/${sid}/news/read`, {ids}); } catch (e) { msvvFail(sid, e); return; }
  for (const it of n.items) if (ids.includes(it.id) && !it.read) { it.read = true; n.unread = Math.max(0, n.unread - 1); }
  renderSide(); renderTop(); if (S.route.mod === 'news') viewSafeRender();
}

// ---- Calendar (month view): the foreign events and due tasks of the shown range, read-only, with the badge
function msvvCalEnsure(from, to) {
  if (!msvvOn()) return;
  const key = from + '|' + to + '|' + S.msvv.links.map(l => l.id).join(',');
  if (S.msvv.cal.key === key && Date.now() - (S.msvv.cal.at || 0) < 5 * MSVV_POLL) return;
  S.msvv.cal = {key, at: Date.now(), ev: {}};
  const c = S.msvv.cal;
  Promise.all(S.msvv.links.map(l => msvvFetch('GET', `/api/servers/${l.id}/events?from=${from}&to=${to}`).then(j => { c.ev[l.id] = msvvArr(j.events); }, () => { c.ev[l.id] = []; })))
    .then(() => { if (S.msvv.cal === c && S.route.mod === 'cal') viewSafeRender(); });
}
function msvvCalItems(d) {
  if (!msvvOn()) return [];
  const out = [];
  for (const l of S.msvv.links) {
    (S.msvv.cal.ev[l.id] || []).forEach((e, i) => { const a = String(e.start || '').slice(0, 10), b = String(e.end || e.start || '').slice(0, 10) || a; if (a && a <= d && d <= (b < a ? a : b)) out.push({sid: l.id, ev: e, i}); });
    for (const t of S.msvv.data[l.id]?.tasks || []) if (t.due === d && !t.parent_id) out.push({sid: l.id, t});
  }
  return out;
}
const msvvCalChip = x => x.t ? `<div class="ev msvev p${msvvPrio(x.t.priority)}" data-msv="${x.sid}:${x.t.id}" role="button" tabindex="0">${msvvBadge(x.sid)}${esc(x.t.title || '')}</div>`
  : `<div class="ev msvev msvcev" data-msvev="${x.sid}:${x.i}" role="button" tabindex="0">${msvvBadge(x.sid)}${esc(x.ev.title || '')}</div>`;
const msvvCalChips = d => msvvCalItems(d).map(msvvCalChip);
function msvvCalDay(d) {
  const it = msvvCalItems(d); if (!it.length) return '';
  return `<div class="msvvcal">${it.map(x => x.t ? msvvRow(x.sid, x.t, {showList: true, tree: false}) : `<button type="button" class="cevrow msvcev" data-msvev="${x.sid}:${x.i}">${msvvBadge(x.sid)}<span>${esc(x.ev.title || '')}</span><span class="muted">${esc(x.ev.all_day ? tr('All day') : msvvTime(x.ev.start))}</span></button>`).join('')}</div>`;
}

// ---- clicks, keys and touches on foreign items (capture: before the own handlers, which would look for data-id)
document.addEventListener('click', e => {
  const t = e.target;
  const fold = t.closest?.('[data-msvv-fold]');
  if (fold) { e.preventDefault(); e.stopPropagation(); const k = 'msvside:' + fold.dataset.msvvFold; if (S.collapsed.has(k)) S.collapsed.delete(k); else S.collapsed.add(k); LS.set('collapsed', [...S.collapsed]); renderSide(); return; }
  const qc = t.closest?.('[data-msvvq]');
  if (qc) { e.preventDefault(); e.stopPropagation(); msvvQPick(qc); return; }
  const nall = t.closest?.('[data-msvnall]');
  if (nall) { e.preventDefault(); e.stopPropagation(); const sid = +nall.dataset.msvnall; msvvNewsRead(sid, (S.msvv.news[sid]?.items || []).filter(x => !x.read).map(x => x.id)); return; }
  const ni = t.closest?.('[data-msvn]');
  if (ni) {
    e.preventDefault(); e.stopPropagation();
    const [sid, ...rest] = ni.dataset.msvn.split(':'), it = (S.msvv.news[+sid]?.items || []).find(x => String(x.id) === rest.join(':'));
    if (!it) return;
    if (!it.read) msvvNewsRead(+sid, [it.id]);
    if (+it.task_id > 0) msvvOpen(+sid, +it.task_id);
    return;
  }
  const ce = t.closest?.('[data-msvev]');
  if (ce) { e.preventDefault(); e.stopPropagation(); const [sid, i] = ce.dataset.msvev.split(':').map(Number), u = msvvUrl(S.msvv.cal.ev[sid]?.[i]?.url); if (u) window.open(u, '_blank', 'noopener'); else toast(msvvName(sid)); return; }
  const r = t.closest?.('[data-msv]');
  if (!r || r.classList.contains('modal') || t.closest('a[href]')) return;
  e.preventDefault(); e.stopPropagation();
  const [sid, id] = r.dataset.msv.split(':').map(Number);
  if (t.closest('[data-msvv="toggle"]')) msvvToggle(sid, id); else msvvOpen(sid, id);
}, true);
document.addEventListener('keydown', e => {
  if (e.target?.id === 'msvv-in' && e.key === 'Enter' && !e.isComposing) {
    e.preventDefault();
    const inp = e.target, txt = inp.value.trim(), {sid, lid} = S.route; if (!txt) return;
    const b = msvvParse(txt); delete b._r; if (!b.title) return;
    inp.value = '';
    msvvAdd(sid, lid, b).then(n => { if (!n) inp.value = txt; const i2 = $('#msvv-in'); if (i2 && !n) i2.value = txt; i2?.focus(); });
    return;
  }
  if ((e.key === 'Enter' || e.key === ' ') && e.target?.closest?.('[data-msv] .ttl, .ev[data-msv], [data-msvev]')) { e.preventDefault(); e.target.click(); }
}, true);
// the own swipe / long press / pull-to-refresh look for data-id: foreign rows keep their touches to themselves
document.addEventListener('touchstart', e => { if (e.target.closest?.('#view [data-msv]')) e.stopPropagation(); }, {capture: true, passive: true});
