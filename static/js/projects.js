/* Kalmido web client: Projects: status, progress, overview, dependencies, custom fields.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ projects (package 3): status, progress, overview
// Progress numbers come with each list in /api/state (definition in kalmido/lists/projects.py: main tasks, or all with the
// setting, all time, won't do / trash left out). The status (owner + edit members, collaboration on) has a
// history (GET /api/lists/<id>/status). The overview is built from the state (works offline).
const STATUSES = [['on_track', N_('On track')], ['at_risk', N_('At risk')], ['off_track', N_('Off track')], ['on_hold', N_('On hold')], ['complete', N_('Complete|status')]];
const statusLabel = st => tr((STATUSES.find(x => x[0] === st) || [0, N_('No status')])[1]);
const pct = p => p.total ? Math.round(100 * p.done / p.total) : 0;
function progBar(p, cls = '') {
  return `<div class="lprog ${cls}" title="${esc(tr('{0} of {1} done ({2}%)', p.done, p.total, pct(p)))}"><div class="pbar"><i style="width:${pct(p)}%"></i></div><span><b>${pct(p)}%</b> ${p.done}/${p.total}</span></div>`;
}
function progMeta(p) {
  return (p.overdue ? `<span class="lmeta over">${trn('{0} overdue', '{0} overdue', p.overdue)}</span>` : '') +
    (p.next_due ? `<span class="lmeta">${tr('Next due: {0}', esc(dayLabel(p.next_due)))}</span>` : '');  // 2.13.0 (#453 P1): says what "next" is
}
function statusPill(l, act = true, empty = l.shared) {
  if (!statusFor(l) || l.is_inbox) return '';
  if (!l.status) return act && empty && canEditList(l.id) ? `<button class="stpill none" data-act="status" data-id="${l.id}">${ic('pulse', 's')}${tr('Set status')}</button>` : '';
  return `<button class="stpill st-${esc(l.status)}" ${act ? `data-act="status" data-id="${l.id}"` : 'disabled'} title="${esc(l.status_note || statusLabel(l.status))}"><i></i>${esc(statusLabel(l.status))}</button>`;
}
function statusNote(l) {
  if (!statusFor(l) || !l.status || !l.status_note) return '';
  return `<div class="lnote"><span>${esc(l.status_note)}</span><span class="muted">${esc([l.status_by_name, l.status_at ? relTime(l.status_at) : ''].filter(Boolean).join(' · '))}</span></div>`;
}
// 2.13.0 (#453 A7): phones (and a folded Fold): the views of a list as a compact segmented control right under the title
// (before: only in "…" with 18 entries); the active one is marked (aria-pressed + fill)
function vsegHtml(l) {
  if (!l || !isMobile()) return '';
  const ch = viewChoices(l); if (ch.length < 2) return '';
  const v = curView(l), short = {overview: N_('Overview')};
  return `<div class="vsegm" role="group" aria-label="${esc(tr('View'))}">${ch.map(([k, n, i]) => `<button type="button" class="${v === k ? 'on' : ''}" data-act="view-${k}" aria-pressed="${v === k}" title="${esc(tr(n))}">${ic(i, 's')}<span>${esc(tr(short[k] || n))}</span></button>`).join('')}</div>`;
}
function listHead(l, o = {}) {
  if (!l || l.is_inbox) return vsegHtml(l) + agBandHtml();
  const p = l.progress || {done: 0, total: 0, overdue: 0}, showP = progressFor(l) && p.total > 0 && !progHidden(l.id), pill = o.noPill ? '' : statusPill(l), ts = timeSumHtml([l]);
  if (!showP && !pill && !ts) return vsegHtml(l) + famBar(l) + lifeBar(l) + agBandHtml();
  return `${vsegHtml(l)}${famBar(l) + lifeBar(l)}<div class="lhead">${showP ? `<span class="lpg">${progBar(p)}<button class="iconbtn lpx" data-act="prog-hide" data-id="${l.id}" title="${tr('Hide progress')}" aria-label="${tr('Hide progress')}">${ic('x', 's')}</button></span>` + progMeta(p) : ''}<span class="spacer"></span>${ts}${pill}</div>${statusNote(l)}${agBandHtml()}`;
}
// ---- 2.7.0 (#407): the tracked time of a project list (or of a folder's project lists) in its header, in hours and in
// working days. Hours per day / shift: the list's own value (list dialog, owner; the same for every member), else the
// server's (Administration; default 8). A number field "Budget h" (agency projects) adds a budget bar: tracked / budget.
// Time tracking on only; the running timer counts along.
const dayHOf = l => +l?.day_hours || S.timeDayH || 8;
const listSecs = lid => (S.timeLists?.[lid]?.s || 0) + (S.timer && S.timer.list_id === lid ? timerElapsed() : 0);
function timeSumHtml(lists) {
  if (!timeOn()) return '';
  const ls = lists.filter(l => l && l.kind === 'project');
  if (!ls.length) return '';
  let sec = 0, days = 0, bud = 0;
  for (const l of ls) { const x = listSecs(l.id); sec += x; days += x / 3600 / dayHOf(l); bud += +(S.timeLists?.[l.id]?.b || 0); }
  if (sec < 60 && !bud) return '';
  const h = sec / 3600, dh = new Set(ls.map(dayHOf));
  const dtxt = Math.abs(days - 1) < .05 ? tr('{0} day|time', fmtNum(1)) : tr('{0} days|time', fmtNum(days));
  const tip = [tr('Tracked: {0}', fmtDur(sec)), dh.size === 1 ? tr('{0} at {1} h per day', dtxt, fmtNum([...dh][0])) : tr('{0}, each list with its own hours per day', dtxt),
    bud ? tr('Budget: {0} h', fmtNum(bud)) : ''].filter(Boolean).join(' · ');
  const pct = bud ? Math.min(100, Math.round(h / bud * 100)) : 0;
  return `<span class="tsum ${bud && h > bud ? 'over' : ''}" title="${esc(tip)}" aria-label="${esc(tip)}">${ic('clock', 's')}<span class="tsl">${tr('Tracked')}</span><b>${esc(fmtNum(h))} h</b><span class="tsd">${esc(dtxt)}</span>${bud ? `<span class="tbud" role="img" aria-label="${esc(tr('{0} % of the budget', Math.round(h / bud * 100)))}"><i style="width:${pct}%"></i></span><span class="tbn">${esc(fmtNum(h))}/${esc(fmtNum(bud))} h</span>` : ''}</span>`;
}
function folderHead(f) {
  const ts = timeSumHtml(folderLists(f));
  return (ts ? `<div class="lhead fhd"><span class="spacer"></span>${ts}</div>` : '') + agBandHtml();
}
async function statusModal(lid) {
  const l = listById(lid); if (!l) return;
  const can = canEditList(lid);
  let sel = l.status || '';
  const md = modal(`<h3>${tr('Project status')} · ${esc(lname(l))}</h3>
    ${can ? `<div class="stchoice">${STATUSES.map(([k, n]) => `<button class="stopt st-${k} ${sel === k ? 'on' : ''}" data-st="${k}"><i></i>${tr(n)}</button>`).join('')}<button class="stopt st-none ${sel ? '' : 'on'}" data-st=""><i></i>${tr('No status')}</button></div>
      <textarea id="st-note" rows="3" maxlength="500" placeholder="${tr('Short update: what is going on, what is needed?')}">${esc(l.status_note || '')}</textarea>
      <div class="shint keep">${collab() && l.shared ? tr('Everyone in this list sees the status and gets it in their News.') : tr('Shown in the list header, the sidebar and the overview.')}</div>`
    : `<div class="rohint">${ic('eye', 's')}${tr('View only')}</div>`}
    <h4>${tr('History')}</h4><div class="sthist" id="st-hist"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button>${can ? `<button class="btn pri" data-m="save">${tr('Update status')}</button>` : ''}</div>`);
  md.classList.add('stmodal');
  rawFetch('GET', `/api/lists/${lid}/status`).then(j => {
    const box = $('#st-hist', md); if (!box) return;
    box.innerHTML = j.items.length ? j.items.map(x => `<div class="shi"><span class="stdot st-${esc(x.status || 'none')}"></span><div><div><b>${esc(x.status ? statusLabel(x.status) : tr('Status cleared'))}</b> <span class="muted">${esc(x.name || tr('Someone'))} · ${esc(fmtWhen(x.created_at))}</span></div>${x.note ? `<div class="shn">${esc(x.note)}</div>` : ''}</div></div>`).join('')
      : `<div class="muted mhint">${tr('No status updates yet.')}</div>`;
  }).catch(e => { const box = $('#st-hist', md); if (box) box.innerHTML = `<div class="muted mhint">${e instanceof Offline ? tr('Only available online.') : esc(e.message)}</div>`; });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.st !== undefined) { sel = b.dataset.st; $$('.stopt', md).forEach(x => x.classList.toggle('on', x === b)); return; }
    if (b.dataset.m === 'close') md.remove();
    if (b.dataset.m === 'save') {
      const was = l.status;
      try { await api('POST', `/api/lists/${lid}/status`, {status: sel, note: $('#st-note', md).value.trim()}); } catch { return; }
      md.remove(); await load(); render(); toast(sel ? tr('Status: {0}', statusLabel(sel)) : tr('Status cleared'));
      if (sel === 'complete' && was !== 'complete') celebrate('project', {name: lname(l)});
    }
  });
}
// ---- "Where is it stuck?" overview (module view, from the state)
S.ov = {only: LS.get('ovOnly', false)};
const riskLists = () => S.lists.filter(l => !l.is_inbox && !l.archived && (l.status === 'at_risk' || l.status === 'off_track'));
const ovProblems = () => statusOn() ? riskLists().length : 0;
function ovRows() {
  const open = openTasks(), t0 = today();
  return S.lists.filter(l => !l.is_inbox && !l.archived && l.kind === 'project').map(l => {
    const ts = open.filter(t => t.list_id === l.id);
    const overdue = ts.filter(t => t.due && t.due < t0).sort((a, b) => a.due.localeCompare(b.due));
    const blocked = depsOn() ? ts.filter(t => t.blocked) : [];
    const unassigned = collab() && l.shared ? ts.filter(t => !t.parent_id && !t.assignee_id) : [];
    const risk = statusFor(l) ? {off_track: 0, at_risk: 1}[l.status] ?? 2 : 2;
    return {l, overdue, blocked, unassigned, risk, bad: overdue.length + blocked.length + unassigned.length + (risk < 2 ? 1 : 0)};
  }).sort((a, b) => a.risk - b.risk || b.overdue.length - a.overdue.length || b.blocked.length - a.blocked.length || bySort(a.l, b.l));
}
function ovTask(t, extra = '') {
  return `<button class="ovt" data-act="open-id" data-id="${t.id}"><span class="chk p${t.priority}"></span><span class="n">${esc(t.title)}</span>${extra}</button>`;
}
const OV_MAX = 6;
function ovMore(arr, fn) {
  return arr.slice(0, OV_MAX).map(fn).join('') + (arr.length > OV_MAX ? `<div class="muted ovmore">${trn('+ {0} more', '+ {0} more', arr.length - OV_MAX)}</div>` : '');
}
function viewOverview() {
  const rows = ovRows(), shown = S.ov.only ? rows.filter(r => r.bad) : rows;
  const sum = k => rows.reduce((n, r) => n + r[k].length, 0);
  const tiles = [[sum('overdue'), tr('overdue'), tr('open tasks past their date')], [sum('blocked'), tr('waiting'), tr('tasks waiting on another task')],
    ...(statusOn() ? [[riskLists().length, tr('at risk'), tr('lists at risk or off track')]] : []),
    ...(collab() && S.lists.some(l => l.shared) ? [[sum('unassigned'), tr('without assignee'), tr('open tasks in shared lists')]] : [])];
  let h = `<div class="stats ovw"><div class="sttiles">${tiles.map(([v, l, s]) => `<div class="${v ? 'hot' : ''}"><b>${v}</b><span>${esc(l)}</span><small>${esc(s)}</small></div>`).join('')}</div>
    <div class="nbar"><div class="seg"><button class="${S.ov.only ? '' : 'on'}" data-act="ov-only" data-k="">${tr('All lists')}</button><button class="${S.ov.only ? 'on' : ''}" data-act="ov-only" data-k="1">${tr('Needs attention')}</button></div></div>`;
  if (!shown.length) return h + `<div class="empty">${ic('done')}${tr('Nothing stuck. No overdue or waiting tasks.')}</div></div>`;
  for (const r of shown) {
    const l = r.l, p = l.progress || {done: 0, total: 0};
    const who = t => t.assignee_id ? personName(l.id, t.assignee_id) || '?' : '';
    let body = '';
    if (r.overdue.length) {
      const groups = new Map();
      for (const t of r.overdue) { const k = collab() && l.shared ? who(t) : ''; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(t); }
      body += `<h4>${ic('clock', 's')}${tr('Overdue')} <span class="c">${r.overdue.length}</span></h4>` + [...groups.entries()].sort((a, b) => (a[0] ? 0 : 1) - (b[0] ? 0 : 1) || a[0].localeCompare(b[0])).map(([k, ts]) =>
        (collab() && l.shared ? `<div class="ovwho"><span class="avatar">${esc(initials(k || '–'))}</span>${esc(k || tr('Nobody'))} <span class="muted">${ts.length}</span></div>` : '') +
        ovMore(ts, t => ovTask(t, `<span class="over">${esc(dayLabel(t.due))}</span>`))).join('');
    }
    if (r.blocked.length) body += `<h4>${ic('lock', 's')}${tr('Waiting')} <span class="c">${r.blocked.length}</span></h4>` + ovMore(r.blocked, t => ovTask(t, `<span class="muted ovw-on">${esc(blockedTitle(t))}</span>`));
    if (r.unassigned.length) body += `<h4>${ic('user', 's')}${tr('Without assignee')} <span class="c">${r.unassigned.length}</span></h4>` + ovMore(r.unassigned, t => ovTask(t, t.due ? `<span class="muted">${esc(dayLabel(t.due))}</span>` : ''));
    h += `<section class="stcard ovcard ${r.risk < 2 ? 'risk st-' + esc(l.status) : ''}"><div class="ovhead"><button class="ovname" data-go="l/${l.id}"><span class="sw" style="${cssColor(l.color) ? 'background:' + cssColor(l.color) : ''}"></span>${esc(lname(l))}${l.shared && collab() ? ic('users', 's') : ''}</button><span class="spacer"></span>${statusPill(l)}</div>
      ${p.total ? `<div class="ovprog">${progBar(p)}${progMeta(p)}</div>` : ''}${statusNote(l)}
      ${body || `<div class="muted ovok">${ic('check', 's')}${tr('Nothing stuck')}</div>`}</section>`;
  }
  return h + `<p class="muted stnote">${tr('Progress: completed vs. all main tasks of the list (subtasks too if set in Settings > General), won’t do and the trash left out, recurring tasks count once. Waiting = at least one task it waits on is still open.')}</p></div>`;
}

// ---- 2.7.1 (#410): the overview of a project list (tab next to List / Kanban / Timeline, project lists only; not the
// "Where is it stuck?" view across all projects). Description (Markdown), key links, milestones, project files + Paperless
// documents of the list, the files of its tasks (read-only), members, status updates and the tracked time. Loaded from
// GET /api/lists/<id>/overview (online); the milestones also come with the list in /api/state (timeline markers).
// Which lists show their overview is remembered per device (LS pov); the list's own view (List / Kanban / Timeline) stays.
S.pov = new Set(LS.get('pov', []));
S.povD = {};  // list id -> {j, v, busy, err}
const povOn = l => !!l && l.kind === 'project' && !l.is_inbox && S.pov.has(l.id);
function isOverview() { return povOn(routeList()); }
function povSet(l, on) {
  if (on) S.pov.add(l.id); else S.pov.delete(l.id);
  LS.set('pov', [...S.pov].slice(-200));
}
async function setListView(l, v) {  // List / Kanban / Timeline (stored on the server) or the overview (this device)
  if (v === 'overview') { povSet(l, true); render(); return; }
  const was = povOn(l);
  povSet(l, false);
  if (v !== listView(l)) { await api('PATCH', '/api/lists/' + l.id, {view: v}); await load(); }
  if (was || v !== listView(l)) render(); else render();
}
// 2.13.0: in projects the overview comes first
const viewChoices = l => [...(l.kind === 'project' && !l.is_inbox ? [['overview', N_('Project overview'), 'brief']] : []), ['list', N_('List'), 'list'], ...(feat('kanban') ? [['kanban', N_('Kanban'), 'kanban']] : []), ...(feat('timeline') ? [['timeline', N_('Timeline'), 'timeline']] : [])];
const curView = l => povOn(l) ? 'overview' : listView(l);
async function povLoad(lid, force) {
  const d = S.povD[lid] || (S.povD[lid] = {});
  if (d.busy || (!force && d.j && d.v === S.v)) return;
  d.busy = true;
  try { d.j = await rawFetch('GET', `/api/lists/${lid}/overview`); d.v = S.v; d.err = ''; }
  catch (e) { if (e.message === 'auth') return; d.err = e instanceof Offline ? 'offline' : e.message; d.v = S.v; }
  finally { d.busy = false; }
  if (routeList()?.id === lid && isOverview()) viewSafeRender();
}
const povHost = u => { try { return new URL(u).host.replace(/^www\./, ''); } catch { return ''; } };
// an icon from the address alone (nothing is fetched from the linked site)
function povLinkIcon(u) {
  const h = povHost(u);
  if (/(^|\.)(github\.com|gitlab\.com|codeberg\.org|bitbucket\.org)$|gitea|forgejo/.test(h)) return 'git';
  if (/figma\.com$|miro\.com$|canva\.com$|sketch\.com$/.test(h)) return 'palette';
  if (/docs\.google\.com$|drive\.google\.com$|dropbox\.com$|onedrive|sharepoint\.com$|nextcloud|box\.com$/.test(h)) return 'folder';
  if (/meet\.|zoom\.us$|teams\.microsoft\.com$/.test(h)) return 'users';
  if (/\.pdf($|\?)/i.test(u)) return 'pdf';
  return 'link';
}
const povFileUrl = (f, dl) => `/api/list-files/${encodeURIComponent(f.id)}${dl ? '?dl=1' : ''}`;
function povFile(f, url, del) {
  const pdf = f.mime === 'application/pdf', img = isImg(f);
  return `<div class="povf"><a href="${url(f, !(pdf || img))}" ${pdf || img ? 'target="_blank" rel="noopener"' : 'download'} title="${esc(f.name)}">${ic(img ? 'file' : pdf ? 'pdf' : 'file')}<span class="pfn">${esc(f.name)}</span><span class="muted pfs">${fmtSize(f.size)}</span></a>${del || ''}</div>`;
}
function povPl(p, del) {
  const cn = !p.hidden && plConn(p.conn);
  if (p.hidden || !plOn() || !cn?.usable) return `<div class="povf">${ic('archive')}<span class="pfn">${tr('Paperless document')}</span><span class="muted pfs">${tr('Linked through a Paperless connection you cannot use')}</span></div>`;
  const sub = [p.correspondent, p.created ? fmtDate(p.created) : ''].filter(Boolean).join(' · ');
  return `<div class="povf"><a href="${esc(cn.url)}/documents/${encodeURIComponent(p.doc_id)}/details" target="_blank" rel="noopener">${ic('archive')}<span class="pfn">${esc(p.title)}</span><span class="muted pfs">${esc(sub)}</span></a>${del || ''}</div>`;
}
const povDel = (k, id, lab) => `<button class="iconbtn povx" data-pov="${k}" data-id="${id}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('x', 's')}</button>`;
function povSec(id, title, body, extra = '') {
  return `<section class="povs" id="pov-${id}"><div class="povh"><h3>${title}</h3><span class="spacer"></span>${extra}</div>${body}</section>`;
}
function viewProjOv() {
  const l = routeList(), d = S.povD[l.id];
  if (!d || (!d.busy && d.v !== S.v)) setTimeout(() => povLoad(l.id), 0);
  const head = `${listHead(l, {noPill: true})}`;  // 2.13.0 (#453 P1): "Set status" only once (in the status section)
  if (!d?.j) return `<div class="pov">${head}<div class="muted mhint">${d?.err ? (d.err === 'offline' ? tr('Only available online.') : esc(d.err)) : tr('Loading…')}</div></div>`;
  const j = d.j, can = !!j.can_edit && !l.archived, t0 = today();
  // description
  const ed = S.povEdit === l.id;
  const desc = ed ? `<textarea id="pov-desc-in" rows="8" maxlength="20000" placeholder="${esc(tr('Goal, scope, contacts, where things are…'))}">${esc(S.drafts['pov:' + l.id] ?? j.description)}</textarea>
      <div class="povbar"><span class="muted">${tr('Markdown')}</span><span class="spacer"></span><button class="btn" data-pov="desc-cancel">${tr('Cancel')}</button><button class="btn pri" data-pov="desc-save">${tr('Save')}</button></div>`
    : j.description ? `<div class="md povmd">${renderMd(j.description, false, {lid: l.id}).replace(/<input type="checkbox"/g, '<input type="checkbox" disabled')}</div>`
      : `<div class="muted povempty">${can ? tr('No description yet. What is this project about, what is the goal?') : tr('No description yet.')}</div>`;
  let h = povSec('desc', tr('Description'), desc, can && !ed ? `<button class="btn sm" data-pov="desc-edit">${ic('edit', 's')}<span>${tr('Edit')}</span></button>` : '');
  // status updates (with collaboration: the existing project status + its history)
  if (statusFor(l)) {
    const hist = (j.status.history || []).slice(0, 5);
    const body = `${hist.length ? `<div class="sthist povst">${hist.map(x => `<div class="shi"><span class="stdot st-${esc(x.status || 'none')}"></span><div><div><b>${esc(x.status ? statusLabel(x.status) : tr('Status cleared'))}</b> <span class="muted">${esc(x.name || tr('Someone'))} · ${esc(fmtWhen(x.created_at))}</span></div>${x.note ? `<div class="shn">${esc(x.note)}</div>` : ''}</div></div>`).join('')}</div>` : `<div class="muted povempty">${tr('No status updates yet.')}</div>`}`;
    h += povSec('status', tr('Status updates'), body, `${l.status ? statusPill(l) : ''}${canEditList(l.id) && !l.archived ? `<button class="btn sm" data-act="status" data-id="${l.id}">${ic('pulse', 's')}<span>${tr('Set status')}</span></button>` : ''}`);
  }
  // milestones
  const ms = j.milestones.map(m => `<div class="povm ${m.done ? 'done' : m.day < t0 ? 'over' : ''}">
      <button class="chk ms ${m.done ? 'on' : ''}" data-pov="ms-done" data-id="${m.id}" role="checkbox" aria-checked="${m.done}" aria-label="${esc(tr('Reached: {0}', m.name))}" ${can ? '' : 'disabled'}>${m.done ? ic('check') : ''}</button>
      <span class="pmn">${S.tasks.has(m.id) ? `<button type="button" class="linkbtn" data-pov="ms-open" data-id="${m.id}" title="${esc(tr('Open the milestone'))}"><span>${esc(m.name)}</span></button>` : `<span>${esc(m.name)}</span>`}</span><span class="pmd">${esc(m.day ? fmtDateLoc(m.day) : tr('No date'))}</span>
      ${can ? `<button class="iconbtn" data-pov="ms-edit" data-id="${m.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit'))}">${ic('edit', 's')}</button>` : ''}</div>`).join('');
  const msMain = povSec('ms', tr('Milestones'), ms || `<div class="muted povempty">${tr('No milestones yet. They also show in the timeline.')}</div>`, can ? `<button class="btn sm" data-pov="ms-add">${ic('plus', 's')}<span>${tr('Add milestone')}</span></button>` : '');
  // files
  const plList = feat('paperless') && (plOn() || j.paperless.length);
  const files = j.files.map(f => povFile(f, povFileUrl, can ? povDel('file-del', f.id, tr('Remove')) : '')).join('') +
    (plList ? j.paperless.map(p => povPl(p, can && !p.hidden && plOn() ? povDel('pl-del', p.id, tr('Remove link')) : '')).join('') : '');
  const fAdd = can ? `<label class="btn sm povup" title="${esc(tr('Images, PDFs, documents'))}">${ic('upload', 's')}<span>${tr('Add file')}</span><input type="file" id="pov-file" multiple hidden></label>${plList && plOn() ? `<button class="btn sm" data-pov="pl-add">${ic('archive', 's')}<span>${tr('Link document')}</span></button>` : ''}` : '';
  const tf = j.task_files.map(f => `<div class="povf"><a href="${attUrl(f, !(f.mime === 'application/pdf' || isImg(f)))}" ${f.mime === 'application/pdf' || isImg(f) ? 'target="_blank" rel="noopener"' : 'download'} title="${esc(f.name)}">${ic(f.mime === 'application/pdf' ? 'pdf' : 'file')}<span class="pfn">${esc(f.name)}</span><span class="muted pfs">${fmtSize(f.size)}</span></a><button class="povt" data-pov="task" data-id="${f.task_id}" title="${esc(tr('Open task'))}">${ic('sub', 's')}<span>${esc(f.task_title)}</span></button></div>`).join('') +
    (feat('paperless') ? j.task_paperless.map(p => povPl(p, `<button class="povt" data-pov="task" data-id="${p.task_id}" title="${esc(tr('Open task'))}">${ic('sub', 's')}<span>${esc(p.task_title)}</span></button>`)).join('') : '');
  const filesSec = povSec('files', tr('Project files'), `<div class="povfl">${files || `<div class="muted povempty">${tr('No project files yet: contracts, briefings, plans.')}</div>`}</div>
      ${can && !isTouch() ? `<div class="muted povdz">${ic('upload', 's')} ${tr('Or drop files here')}</div>` : ''}
      ${tf ? `<details class="povtf" ${LS.get('povTf', true) ? 'open' : ''}><summary>${tr('Attachments from tasks')} <span class="muted">${j.task_files.length + (feat('paperless') ? j.task_paperless.length : 0)}</span></summary><div class="povfl">${tf}</div></details>` : ''}`, fAdd);
  // side: key links, members, time
  const links = j.links.map((x, i) => `<div class="povl"><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer" title="${esc(x.url)}">${ic(povLinkIcon(x.url), 's')}<span class="pln">${esc(x.title)}</span><span class="muted plh">${esc(povHost(x.url))}</span></a>
      ${can ? `<span class="povlb">${i ? `<button class="iconbtn" data-pov="link-up" data-id="${x.id}" title="${esc(tr('Move up'))}" aria-label="${esc(tr('Move up'))}">${ic('chev', 's up')}</button>` : ''}<button class="iconbtn" data-pov="link-edit" data-id="${x.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit'))}">${ic('edit', 's')}</button></span>` : ''}</div>`).join('');
  let side = povSec('links', tr('Key links'), links || `<div class="muted povempty">${tr('Repository, designs, documents: the addresses everyone needs.')}</div>`, can ? `<button class="btn sm" data-pov="link-add">${ic('plus', 's')}<span>${tr('Add link')}</span></button>` : '');
  if (collab() && j.members.length) {
    side += povSec('people', tr('Members'), `<div class="povp">${j.members.map(p => `<div class="povpm">${avBtn(p.user_id, p.name)}<span class="ppn">${esc(p.name)}${S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : ''}</span><span class="muted">${esc(roleLabel(p.role))}</span></div>`).join('')}</div>`,
      canManage(l) && !l.archived ? `<button class="btn sm" data-act="share-list" data-id="${l.id}">${ic('users', 's')}<span>${tr('Share…')}</span></button>` : '');
  }
  // 2.17.0 (#442): the project's notes (newest first) and its team chat
  if (notesOn(l)) { const ns = notesOf(l.id).slice(0, 6);
    side += povSec('notes', tr('Notes'), ns.length ? `<ul class="povnotes">${ns.map(n => `<li><a href="#note/${n.id}">${n.pinned ? ic('pin', 's') : ic('edit', 's')}<span>${esc(n.title)}</span><time class="muted">${esc(relTime(n.updated_at))}</time></a></li>`).join('')}</ul>` : `<div class="muted povempty">${tr('Meeting notes, briefings, decisions: write them next to the tasks.')}</div>`,
      `<a class="btn sm" href="#notes/${l.id}">${ic('edit', 's')}<span>${notesOf(l.id).length ? tr('All notes') : tr('New note')}</span></a>`); }
  if (teamOn() && l.shared) side += povSec('chat', tr('Team chat'), `<button type="button" class="btn sm" data-act="list-chat" data-id="${l.id}">${ic('comment', 's')}<span>${tr('Open the list chat')}</span></button>`);
  const ts = timeSumHtml([l]);
  if (timeOn() && j.time) side += povSec('time', tr('Tracked time'), ts || `<div class="muted povempty">${tr('No time tracked yet.')}</div>`);
  return `<div class="pov">${head}<div class="povg"><div class="povc">${h}${msMain}${filesSec}</div><div class="povc povside">${side}</div></div></div>`;
}
async function povApi(method, url, body) {
  const lid = routeList()?.id;
  const r = await api(method, url, body);
  if (r && r.list_id === lid && r.links) { S.povD[lid] = {j: r, v: S.v}; renderView(); }
  else povLoad(lid, true);
  return r;
}
function povLinkModal(l, x) {
  const md = modal(`<h3>${x ? tr('Edit link') : tr('Add link')}</h3>
    <div class="row"><label for="pl-url">${tr('Address')}</label><input id="pl-url" type="url" inputmode="url" placeholder="https://…" value="${esc(x?.url || '')}" maxlength="2000"></div>
    <div class="row"><label for="pl-ttl">${tr('Title')}</label><input id="pl-ttl" maxlength="120" placeholder="${esc(tr('e.g. Repository, Designs'))}" value="${esc(x?.title || '')}"></div>
    <div class="foot">${x ? `<button class="btn danger" data-m="del">${tr('Remove')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('povmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      if (b.dataset.m === 'del') await povApi('DELETE', `/api/lists/${l.id}/links/${x.id}`);
      else await povApi(x ? 'PATCH' : 'POST', `/api/lists/${l.id}/links${x ? '/' + x.id : ''}`, {url: $('#pl-url', md).value.trim(), title: $('#pl-ttl', md).value.trim()});
    } catch { return; }
    md.remove();
  });
  if (!isMobile()) setTimeout(() => $('#pl-url', md)?.focus(), 30);
}
function povMsModal(l, m) {
  const md = modal(`<h3>${m ? tr('Edit milestone') : tr('Add milestone')}</h3>
    <div class="row"><label for="pm-name">${tr('Name')}</label><input id="pm-name" maxlength="120" placeholder="${esc(tr('e.g. Launch, Handover'))}" value="${esc(m?.name || '')}"></div>
    <div class="row"><label for="pm-day">${tr('Date')}</label>${dateIn('pm-day', m?.day || '', {label: tr('Date'), clear: false})}</div>
    <div class="foot">${m ? `<button class="btn danger" data-m="del">${tr('Remove')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('povmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      if (b.dataset.m === 'del') await povApi('DELETE', `/api/lists/${l.id}/milestones/${m.id}`);
      else {
        const day = $('#pm-day', md).value;
        if (!day) { toast(tr('Pick a date')); return; }
        await povApi(m ? 'PATCH' : 'POST', `/api/lists/${l.id}/milestones${m ? '/' + m.id : ''}`, {name: $('#pm-name', md).value.trim(), day});
      }
    } catch { return; }
    md.remove(); await load(); render();  // the timeline markers come with the list
  });
  if (!isMobile()) setTimeout(() => $('#pm-name', md)?.focus(), 30);
}
async function povUpload(l, files) {
  files = noEmpty(files);
  if (!files.length) return;
  const max = 50 * 1024 * 1024, big = files.find(f => f.size > max);
  if (big) { toast(tr('{0} is larger than 50 MB', big.name)); return; }
  const fd = new FormData();
  files.forEach(f => fd.append('file', f, f.name));
  toast(files.length === 1 ? tr('Uploading…') : tr('Uploading {0} files…', files.length));
  try { await povApi('POST', `/api/lists/${l.id}/files`, fd); toast(files.length === 1 ? tr('Attached') : tr('{0} files attached', files.length)); } catch { /* shown */ }
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-pov]'); if (!b || !b.closest('.pov')) return;
  const l = routeList(), d = l && S.povD[l.id], j = d?.j; if (!j) return;
  const id = +b.dataset.id || 0;
  switch (b.dataset.pov) {
    case 'desc-edit': S.povEdit = l.id; renderView(); setTimeout(() => { const t = $('#pov-desc-in'); if (t) { t.focus(); autosize(t); } }, 20); break;
    case 'desc-cancel': S.povEdit = null; delete S.drafts['pov:' + l.id]; renderView(); break;
    case 'desc-save': { const v = $('#pov-desc-in')?.value ?? ''; S.povEdit = null; try { await povApi('PATCH', `/api/lists/${l.id}/overview`, {description: v}); } catch { S.povEdit = l.id; return; } delete S.drafts['pov:' + l.id]; renderView(); toast(tr('Saved')); break; }
    case 'link-add': povLinkModal(l, null); break;
    case 'link-edit': povLinkModal(l, j.links.find(x => x.id === id)); break;
    case 'link-up': { const ids = j.links.map(x => x.id), i = ids.indexOf(id); if (i > 0) { [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]]; try { await povApi('PUT', `/api/lists/${l.id}/links/order`, {ids}); } catch { /* shown */ } } break; }
    case 'ms-add': povMsModal(l, null); break;
    case 'ms-edit': povMsModal(l, j.milestones.find(x => x.id === id)); break;
    case 'ms-open': openDetail(id); break;  // 2.18.0 (#430): milestones are tasks (progress, burndown, release notes there)
    case 'ms-done': { const m = j.milestones.find(x => x.id === id); if (!m) break; try { await povApi('PATCH', `/api/lists/${l.id}/milestones/${id}`, {done: !m.done}); } catch { return; } await load(); render(); break; }
    case 'file-del': { const f = j.files.find(x => x.id === id); if (!f || !await askConfirm(tr('Delete “{0}”?', f.name), tr('The file is removed for everyone in this project.'), {ok: tr('Delete'), danger: true})) break; try { await povApi('DELETE', `/api/list-files/${id}`); } catch { /* shown */ } break; }
    case 'pl-add': plSearchModal(0, {linked: new Set(j.paperless.filter(p => !p.hidden).map(p => `${p.conn || 0}:${p.doc_id}`)), pick: async (doc, conn) => { await povApi('POST', `/api/lists/${l.id}/paperless`, {doc_id: doc, conn}); }}); break;
    case 'pl-del': try { await povApi('DELETE', `/api/lists/${l.id}/paperless/${id}`); } catch { /* shown */ } break;
    case 'task': if (S.tasks.get(id)) openDetail(id); else go('t/' + id); break;
  }
});
document.addEventListener('input', e => { if (e.target.id === 'pov-desc-in') { const l = routeList(); if (l) S.drafts['pov:' + l.id] = e.target.value; } });  // 2.12.2 (#453 B3): the draft survives any re-render
document.addEventListener('change', e => {
  if (e.target.id === 'pov-file') { const l = routeList(); if (l) povUpload(l, e.target.files); e.target.value = ''; }
});
document.addEventListener('toggle', e => { if (e.target.classList?.contains('povtf')) LS.set('povTf', e.target.open); }, true);
// 2.7.2: drag files from the desktop onto "Project files" (editors only, i.e. where "Add file" is shown)
const povDropZone = e => { const z = e.target.closest?.('#pov-files'); return z && z.querySelector('#pov-file') && [...(e.dataTransfer?.types || [])].includes('Files') ? z : null; };
document.addEventListener('dragover', e => { const z = povDropZone(e); if (!z) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; z.classList.add('povdrop'); });
document.addEventListener('dragleave', e => { const z = e.target.closest?.('#pov-files'); if (z && !z.contains(e.relatedTarget)) z.classList.remove('povdrop'); });
document.addEventListener('drop', e => {
  const z = povDropZone(e); if (!z) return;
  e.preventDefault(); z.classList.remove('povdrop');
  const l = routeList(); if (l) povUpload(l, e.dataTransfer.files);
});

// ------------------------------------------------------------------ dependencies (detail panel, package 3)
S.dp = {id: null};
async function loadDeps(id) {
  if (!(id > 0) || !depsOn() || S.tasks.get(id)?.context) return;
  const v = S.v;
  try { const j = await rawFetch('GET', `/api/tasks/${id}/deps`); if (S.sel === id) { S.dp = {...j, id, v}; drawDeps(); } }
  catch (e) { if (e.message !== 'auth' && S.sel === id) { S.dp = {id, v, err: e instanceof Offline ? 'offline' : e.message}; drawDeps(); } }
}
function drawDeps() { const el = $('#d-deps'), t = taskById(S.sel); if (el && t) el.innerHTML = depsHtml(t); }
function depItem(x, dir, t, ro) {
  if (x.hidden) return `<div class="dep hid">${ic('lock', 's')}<span class="muted">${tr('a task you cannot see')}${x.status === 0 && dir === 'by' ? ' · ' + tr('open') : ''}</span>${!ro && dir === 'by' ? `<button class="iconbtn" data-act="dep-rm" data-id="${t.id}" data-b="0" title="${tr('Remove')}">${ic('x', 's')}</button>` : ''}</div>`;
  const rm = dir === 'by' ? !ro : canEditList(x.list_id);
  return `<div class="dep ${x.status ? 'done' : ''}"><span class="dst ${x.status === 2 ? 'on' : x.status === -1 ? 'wont' : ''}">${x.status === 2 ? ic('check', 's') : x.status === -1 ? ic('x', 's') : ''}</span><button class="dt" data-act="open-dep" data-id="${x.id}">${esc(x.title)}</button><span class="muted dl">${esc(lname(listById(x.list_id)))}${x.due && !x.status ? ' · ' + esc(dayLabel(x.due)) : ''}</span>${rm ? `<button class="iconbtn" data-act="dep-rm" data-id="${dir === 'by' ? t.id : x.id}" data-b="${dir === 'by' ? x.id : t.id}" title="${tr('Remove')}">${ic('x', 's')}</button>` : ''}</div>`;
}
function depsHtml(t) {
  const D = S.dp.id === t.id ? S.dp : null, ro = !canEdit(t);
  const head = `<h5>${tr('Dependencies')}${t.blocked && !t.status ? ` <span class="blk">${ic('lock', 's')}${tr('waiting')}</span>` : ''}</h5>`;
  if (!D) return head + `<div class="muted mhint">${tr('Loading…')}</div>`;
  if (D.err) return head + `<div class="muted mhint">${D.err === 'offline' ? tr('Dependencies are only available online.') : esc(D.err)}</div>`;
  const add = dir => ro ? '' : `<button class="btn sm dadd" data-act="dep-add" data-dir="${dir}" data-id="${t.id}">${ic('plus', 's')} ${dir === 'by' ? tr('Waiting on…') : tr('Blocking…')}</button>`;
  if (ro && !D.blocked_by.length && !D.blocking.length) return head + `<div class="muted mhint">${tr('No dependencies.')}</div>`;
  return head + `<div class="dgrp"><div class="dlab">${tr('Waiting on')}</div>${D.blocked_by.map(x => depItem(x, 'by', t, ro)).join('')}${add('by')}${waitExtHtml(t, ro)}</div>
    <div class="dgrp"><div class="dlab">${tr('Blocking')}</div>${D.blocking.map(x => depItem(x, 'blocking', t, ro)).join('')}${add('blocking')}</div>`;
}
// 2.22.0 (#686): "Waiting on external" (a client's approval, an offer, a delivery) as a visible button in the task panel:
// in the dependencies under "Waiting on…" (the tasks), else in its own small section; hidden while the task already
// waits (the waiting bar at the top shows it then)
function waitExtHtml(t, ro, own) {
  if (ro || !t || t.id <= 0 || t.context || t.status !== 0 || t.waiting_at) return '';
  const b = `<button class="btn sm dadd dwait" data-act="wait-edit" data-id="${t.id}">${ic('hourglass', 's')} ${tr('Waiting on external…')}</button>`;
  return own ? `<div class="dsec waitsec"><h5>${tr('Waiting')}</h5>${b}</div>` : b;
}
function depPicker(tid, dir) {
  const D = S.dp.id === tid ? S.dp : {blocked_by: [], blocking: []};
  const have = new Set((dir === 'by' ? D.blocked_by : D.blocking).filter(x => x.id).map(x => x.id));
  const self = taskById(tid);
  const md = modal(`<h3>${dir === 'by' ? tr('Waiting on…') : tr('Blocking…')}</h3>
    <div class="shint keep">${dir === 'by' ? tr('“{0}” can only really start once the chosen task is done.', esc(self?.title || '')) : tr('The chosen task waits on “{0}”.', esc(self?.title || ''))}</div>
    <input id="dp-q" placeholder="${tr('Search open tasks')}" autocomplete="off" style="width:100%;margin-top:.5rem">
    <div class="dplist tpk" id="dp-list" role="listbox" aria-label="${esc(tr('Open tasks'))}"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button></div>`);
  md.classList.add('dpmodal');
  const draw = () => {
    const q = norm($('#dp-q', md).value || '');
    const arr = openTasks().filter(x => x.id > 0 && x.id !== tid && !have.has(x.id) && isProject(x.list_id) && (dir === 'by' || canEdit(x)) && (!q || norm(x.title).includes(q)))
      .sort((a, b) => (b.list_id === self?.list_id) - (a.list_id === self?.list_id) || (a.due || '9999').localeCompare(b.due || '9999') || bySort(a, b)).slice(0, 60);
    // 2.22.0 (#685): rows grow with their text (title at most two lines, the list small below), grouped: this list first,
    // then the other lists under their name; the same look as every task picker (.tpk)
    const row = x => `<button type="button" class="tpkrow" role="option" data-pick="${x.id}"><span class="tpkt">${esc(x.title)}</span><span class="tpkm">${esc(lname(listById(x.list_id)))}${x.due ? ' · ' + esc(dayLabel(x.due)) : ''}</span></button>`;
    const same = arr.filter(x => x.list_id === self?.list_id), others = arr.filter(x => x.list_id !== self?.list_id);
    const byList = [...new Set(others.map(x => x.list_id))];
    $('#dp-list', md).innerHTML = !arr.length ? `<div class="muted mhint">${tr('No matching open task.')}</div>`
      : (same.length ? `<div class="tpkg" role="group" aria-label="${esc(tr('This list'))}"><div class="tpkh">${esc(tr('This list'))}</div>${same.map(row).join('')}</div>` : '')
        + byList.map(lid => `<div class="tpkg" role="group" aria-label="${esc(lname(listById(lid)))}"><div class="tpkh">${esc(lname(listById(lid)))}</div>${others.filter(x => x.list_id === lid).map(row).join('')}</div>`).join('');
  };
  draw();
  md.addEventListener('input', e => { if (e.target.id === 'dp-q') draw(); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.pick) {
      const x = +b.dataset.pick;
      try { await api('POST', '/api/deps', dir === 'by' ? {task_id: tid, blocker_id: x} : {task_id: x, blocker_id: tid}); } catch { return; }
      md.remove(); await load(); render(); loadDeps(tid);
    }
  });
  setTimeout(() => { if (!isMobile()) $('#dp-q', md).focus(); }, 50);
}
const blockedNames = t => { const n = (t.blockers || []).map(id => S.tasks.get(id)?.title).filter(Boolean); const h = Math.max(0, (t.blocked || 0) - n.length); return [...n.map(x => tr('“{0}”|quoted', x)), ...(h ? [trn('{0} task you cannot see', '{0} tasks you cannot see', h)] : [])].join(', '); };

// ------------------------------------------------------------------ custom fields (package 3)
const FTYPES = [['text', N_('Text')], ['number', N_('Number')], ['select', N_('Selection')], ['date', N_('Date')], ['checkbox', N_('Checkbox')], ['person', N_('Person')], ['url', N_('Link')]];
const FT_ICON = {text: 'edit', number: 'chart', select: 'list', date: 'cal', checkbox: 'check', person: 'user', url: 'link'};
const ftLabel = t => tr((FTYPES.find(x => x[0] === t) || [0, t])[1]);
function fieldEditor(f, t, ro) {
  const v = t.fields?.[f.id] ?? '', id = `cf-${f.id}`, dis = ro ? 'disabled' : '';
  let c;
  switch (f.type) {
    case 'number': c = `<span class="cfnum"><input id="${id}" data-cf="${f.id}" inputmode="decimal" value="${esc(v === '' ? '' : (+v).toLocaleString(LOCALE(), {useGrouping: false, maximumFractionDigits: 6}))}" ${ro ? 'readonly' : ''} placeholder="–">${f.options?.unit ? `<span class="muted">${esc(f.options.unit)}</span>` : ''}</span>`; break;
    case 'select': c = `<select id="${id}" data-cf="${f.id}" ${dis}><option value="">–</option>${(f.options?.options || []).map(o => `<option value="${esc(o.id)}" ${o.id === v ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>`; break;
    case 'date': c = dateIn(id, v, {attrs: `data-cf="${f.id}"`, ro, label: f.name, empty: '–'}); break;
    case 'checkbox': c = `<span><input id="${id}" type="checkbox" data-cf="${f.id}" ${v === '1' ? 'checked' : ''} ${dis}></span>`; break;
    case 'person': c = `<select id="${id}" data-cf="${f.id}" ${dis}><option value="">–</option>${listPeople(listById(t.list_id)).map(p => `<option value="${p.user_id}" ${String(p.user_id) === v ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`; break;
    case 'url': c = `<span class="cfurl"><input id="${id}" type="url" inputmode="url" data-cf="${f.id}" value="${esc(v)}" placeholder="https://…" ${ro ? 'readonly' : ''}>${v ? `<a class="iconbtn" href="${esc(v)}" target="_blank" rel="noopener noreferrer" title="${esc(v)}">${ic('link', 's')}</a>` : ''}</span>`; break;
    default: c = `<input id="${id}" data-cf="${f.id}" value="${esc(v)}" maxlength="1000" ${ro ? 'readonly' : ''} placeholder="–">`;
  }
  return `<label for="${id}" title="${esc(ftLabel(f.type))}">${esc(f.name)}</label>${c}`;
}
// typed number -> "1234.5": German "1.234,5" / "12,5" / "12.5", English "1,234.5"
function numIn(v) {
  v = v.replace(/[\s\u00a0\u202f']/g, '');
  if (!LOCALE().startsWith('de')) return v.replace(/,/g, '');
  if (v.includes(',')) return v.replace(/\./g, '').replace(',', '.');
  return (v.match(/\./g) || []).length > 1 ? v.replace(/\./g, '') : v;
}
async function saveField(el) {
  const t = taskById(S.sel), fid = +el.dataset.cf, f = fieldById(fid); if (!t || !f) return;
  if (!canEdit(t)) { roToast(); renderDetail(); return; }
  let v = f.type === 'checkbox' ? (el.checked ? '1' : null) : (el.value || '').trim() || null;
  if (v && f.type === 'url' && !/^https?:\/\//i.test(v) && /^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(v)) v = 'https://' + v;
  if (v && f.type === 'number') v = numIn(v);
  if ((t.fields?.[fid] ?? null) === v) return;
  try { await patchTask(t.id, {fields: {[fid]: v}}); } catch { renderDetail(); }
}
function fieldModal(lid, f, done) {
  const edit = !!f, st = {type: f?.type || 'text', opts: JSON.parse(JSON.stringify(f?.options?.options || [{id: '', name: '', color: LCOLORS[1]}]))};
  const md = modal(`<h3>${edit ? tr('Edit field') : tr('New field')}</h3>
    <div class="row"><label for="fd-name">${tr('Name')}</label><input id="fd-name" value="${esc(f?.name || '')}" maxlength="60" placeholder="${tr('e.g. Budget, Stage, Client')}"></div>
    <div class="row"><label for="fd-type">${tr('Type')}</label><select id="fd-type" ${edit ? 'disabled' : ''}>${FTYPES.map(([k, n]) => `<option value="${k}" ${st.type === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div id="fd-extra"></div>
    <div class="row" ${colCfg(lid) ? 'hidden' : ''}><label>${tr('Task rows')}</label><label class="chkl"><input type="checkbox" id="fd-pin" ${f?.pinned ? 'checked' : ''}> ${tr('show as a chip (at most 2 fields)')}</label></div>
    <div class="foot">${edit ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  const extra = () => {
    const x = $('#fd-extra', md);
    if (st.type === 'number') x.innerHTML = `<div class="row"><label for="fd-unit">${tr('Unit')}</label><input id="fd-unit" value="${esc(f?.options?.unit || '')}" maxlength="12" placeholder="${tr('optional, e.g. € or h')}" style="max-width:8.75rem"></div>`;
    else if (st.type === 'select') x.innerHTML = `<h4>${tr('Options')}</h4><div class="optlist">${st.opts.map((o, i) => `<div class="optrow" data-i="${i}"><button class="swc" data-ocol="${i}" style="background:${cssColor(o.color) || 'var(--bg4)'}" title="${tr('Color')}"></button><input data-oname="${i}" value="${esc(o.name)}" maxlength="60" placeholder="${tr('Option')}"><button class="iconbtn" data-orm="${i}" title="${tr('Remove')}">${ic('x', 's')}</button></div>`).join('')}</div><button class="btn sm" data-m="opt-add">${ic('plus', 's')} ${tr('Option')}</button>${edit ? `<div class="shint keep">${tr('Removing an option clears it in all tasks.')}</div>` : ''}`;
    else x.innerHTML = st.type === 'person' ? `<div class="shint keep">${tr('Pick the owner or a member of the list.')}</div>` : '';
  };
  extra();
  md.addEventListener('change', e => { if (e.target.id === 'fd-type') { st.type = e.target.value; extra(); } });
  md.addEventListener('input', e => { const i = e.target.dataset.oname; if (i !== undefined) st.opts[+i].name = e.target.value; });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.ocol !== undefined) { const o = st.opts[+b.dataset.ocol]; o.color = LCOLORS[(LCOLORS.indexOf(o.color || '') + 1) % LCOLORS.length]; extra(); return; }
    if (b.dataset.orm !== undefined) { st.opts.splice(+b.dataset.orm, 1); extra(); return; }
    const a = b.dataset.m;
    if (a === 'opt-add') { st.opts.push({id: '', name: '', color: LCOLORS[(st.opts.length % (LCOLORS.length - 1)) + 1]}); extra(); $$('[data-oname]', md).pop()?.focus(); return; }
    if (a === 'close') { md.remove(); return; }
    if (a === 'del') {
      const n = [...S.tasks.values()].filter(t => t.fields?.[f.id] != null).length;
      if (!await askConfirm(tr('Delete the field “{0}”?', f.name), tr('Its values are deleted in all tasks.') + (n ? ' ' + trn('({0} task with a value)', '({0} tasks with a value)', n) : ''), {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', '/api/fields/' + f.id); } catch { return; }
      md.remove(); await load(); render(); done && done(); return;
    }
    if (a === 'save') {
      const name = $('#fd-name', md).value.trim(); if (!name) { need($('#fd-name', md)); return; }
      const options = st.type === 'number' ? {unit: $('#fd-unit', md).value.trim()} : st.type === 'select' ? {options: st.opts.filter(o => o.name.trim())} : {};
      const body = {name, options, pinned: $('#fd-pin', md).checked};
      try { await api(edit ? 'PATCH' : 'POST', edit ? '/api/fields/' + f.id : `/api/lists/${lid}/fields`, edit ? body : {...body, type: st.type}); } catch { return; }
      md.remove(); await load(); render(); done && done();
    }
  });
  setTimeout(() => $('#fd-name', md).focus(), 50);
}
function fieldsBox(lid) {
  const fs = fieldsAll(lid);
  return fs.map((f, i) => `<div class="mrow" data-fid="${f.id}">${ic(FT_ICON[f.type] || 'edit', 's')}<span class="n">${esc(f.name)}</span><span class="muted">${esc(ftLabel(f.type))}</span>
    <button class="iconbtn ${f.pinned ? 'on' : ''}" data-fpin="${f.id}" title="${tr('Show as a chip on the task rows')}">${ic('pin', 's')}</button>
    <button class="iconbtn" data-fup="${f.id}" title="${tr('move up')}" ${i ? '' : 'disabled'}>${ic('chev', 's up')}</button>
    <button class="iconbtn" data-fedit="${f.id}" title="${tr('Edit')}">${ic('edit', 's')}</button></div>`).join('') +
    `<div class="mrow"><button class="btn sm" data-m="field-add">${ic('plus', 's')} ${tr('Field')}</button>${fs.length ? '' : hintOnce('fields', tr('Own columns for this list: budget, stage, client, …'))}</div>`;
}
// filter engine: rules.cf = {field id: {sel: [option ids]} | {chk: ['1', '0']} | {date: [DATE_OPTS]} | {num: {op, v}}}
const cfRuleOn = r => !!r && (r.sel?.length || r.chk?.length || r.date?.length || (r.num && (r.num.op === 'set' || r.num.op === 'empty' || (r.num.op && r.num.v !== '' && r.num.v != null))));
function cfMatch(t, fid, r) {
  const f = fieldById(+fid); if (!f || f.list_id !== t.list_id) return false;
  const v = t.fields?.[fid] ?? null;
  if (r.sel?.length) return r.sel.includes(v ?? '');
  if (r.chk?.length) return r.chk.includes(v === '1' ? '1' : '0');
  if (r.date?.length) return r.date.some(d => dateMatch({due: v}, d));
  if (r.num) {
    if (r.num.op === 'empty') return v == null;
    if (v == null) return false;
    const x = +v, y = +String(r.num.v).replace(',', '.');
    return r.num.op === 'set' || (r.num.op === 'gt' ? x > y : r.num.op === 'lt' ? x < y : r.num.op === 'eq' ? x === y : true);
  }
  return true;
}
function cfSortCmp(fid) {
  const f = fieldById(fid);
  if (!f) return bySort;
  const key = t => {
    const v = t.fields?.[fid]; if (v == null) return null;
    if (f.type === 'number') return +v;
    if (f.type === 'select') return (f.options?.options || []).findIndex(o => o.id === v);
    if (f.type === 'checkbox') return 0;
    if (f.type === 'person') return (personName(t.list_id, +v) || '').toLowerCase();
    return String(v).toLowerCase();
  };
  return (a, b) => { const x = key(a), y = key(b); if (x === y) return b.priority - a.priority || bySort(a, b); if (x == null) return 1; if (y == null) return -1; return x < y ? -1 : 1; };
}
function actField(d) {
  if (d.v == null) return '';
  if (d.type === 'number') return numFmt(d.v) + (d.unit ? ' ' + d.unit : '');
  if (d.type === 'date') return fmtDayAbs(d.v);
  if (d.type === 'checkbox') return tr('yes');
  if (d.type === 'url') return urlHost(d.v);
  return String(d.v);
}
