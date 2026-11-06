// 2.28.0 (#935): workspaces -- "Private" and the organisations a person belongs to. Every list has one (list.org_id, null =
// private); the sidebar's switch (setting "workspace": all | private | org:<id>, followed on every device) shows the lists,
// tasks, News, agents and team chats of ONE workspace, "All" shows everything. The inbox is always there. The server keeps
// the boundary between people (an organisation's list is shared only inside it, agents join only lists of their workspace);
// this module only decides what the app shows. 2.30.0 (#1036): calendars and address books have a workspace too (org_id):
// the switch shows only their events and contacts (wsObjIn); their dialogs choose it like the list dialog (wsAskNew,
// wsMoveMenu).
// 2.28.0 (#985): the bot badge on an agent's picture (botBadge), (#987) what counts as "For you" at the bell (bellCount).
const wsOn = () => !!S.workspaces && !!(S.me?.workspaces || []).length;
const wsCur = () => { const v = S.settings?.workspace || 'all'; return wsOn() && (v === 'private' || (v.startsWith('org:') && (S.me.workspaces || []).some(w => 'org:' + w.id === v))) ? v : 'all'; };
const wsOf = l => !l || !l.org_id ? 'private' : 'org:' + l.org_id;
const inWs = (l, ws = wsCur()) => ws === 'all' || !l || !!l.is_inbox || wsOf(l) === ws;
// a task of a list outside the shown workspace is hidden everywhere except in that list itself (like an archived list's)
// 2.49.0 (#1770): no exception for the open list any more -- a list is only shown inside its own workspace (wsFollow)
const wsHidden = t => wsCur() !== 'all' && !!t && !inWs(listById(t.list_id));
const wsOrg = id => (S.me?.workspaces || []).find(w => w.id === +id);
const wsName = ws => ws === 'all' ? tr('All workspaces') : ws === 'private' ? tr('Private|workspace') : (wsOrg(ws.slice(4))?.name || tr('Organisation'));
// 2.87.9 (#1913): an organisation's symbol -- its own picture, else its emoji, else fb (the workspace switch, Settings, the admin list)
const orgIconHtml = (o, fb = ic('brief', 's')) => o?.icon_url ? `<img class="orgic" src="${esc(o.icon_url)}" alt="" loading="lazy" decoding="async">`
  : o?.icon ? `<span class="wsemo" aria-hidden="true">${esc(o.icon)}</span>` : fb;
const wsIcon = ws => ws === 'private' ? ic('home', 's') : ws === 'all' ? ic('grid', 's') : orgIconHtml(wsOrg(ws.slice(4)));
const wsOptions = () => ['private', ...(S.me?.workspaces || []).map(w => 'org:' + w.id), 'all'];
const wsObjIn = (o, ws = wsCur()) => ws === 'all' || !o || wsOf(o) === ws;
const wsAgentIn = (a, ws = wsCur()) => ws === 'all' || !a || (ws === 'private' ? !a.org_id : 'org:' + a.org_id === ws);
const wsLabel = (org_id) => org_id ? (wsOrg(org_id)?.name || tr('Organisation')) : tr('Private|workspace');
// 2.66.1 (#1945): views that keep data of ONE workspace which they cannot check themselves when drawing (the server picks the
// area from the saved setting) register here: wsSet() calls fn(false) before it draws again and fn(true) once the server
// knows the new workspace. Views that compare their own workspace when drawing (docs, files, office, clients) or load again
// with the new state (absences, disposition: core.js) need no entry.
// The guard test p2661_b_ui lists every view with a workspace link.
const p61b_WS = {};
const p61b_wsOn = (name, fn) => { p61b_WS[name] = fn; };
const p61b_wsRun = after => { for (const [n, fn] of Object.entries(p61b_WS)) { try { fn(after); } catch (x) { console.error('workspace switch', n, x); } } };
// 2.397.0 (#3404): every workspace keeps its state on this device (LS wsView = {'private' | 'org:<id>': {...}}): the sidebar's
// open groups and folders and the per-device choices of its areas (WSV_KEYS). "All workspaces" has none: nothing done there
// is written back. WSV = the workspace route() drew last.
// 2.497.0 (#4048): the page itself is no longer kept per workspace (it was #3404's target rule): a switch stays in the area
// shown (ws_target); the scroll position of a view per workspace comes from viewmem.js (the workspace is part of its key)
const WSV_KEYS = ['lastKey', 'sbbLast', 'mgTab', 'ofmLast', 'sideOpenG', 'sideGroups', 'sbbOpen', 'newsFilter', 'newsKind', 'jobsFilter'];
const WSV = {ws: ''};
const wsv_hashNow = () => location.hash.slice(1) || keyToHash(S.route?.key || START_KEY);
const wsv_folders = ws => folderNames().filter(f => S.lists.some(l => !l.is_inbox && fUnder(l.folder, f) && wsOf(l) === ws));
function wsv_save(ws) {
  if (!ws || ws === 'all' || !wsOn()) return;
  const all = LS.get('wsView', {}) || {};
  all[ws] = {ls: Object.fromEntries(WSV_KEYS.map(k => [k, LS.get(k, null)])), shut: wsv_folders(ws).filter(f => foldClosed(f))};
  LS.set('wsView', all);
}
// route(): before a new page replaces the one of the same workspace (after it: wsv_seen)
const wsv_leave = () => { if (WSV.ws && WSV.ws === wsCur()) wsv_save(WSV.ws); };
const wsv_seen = () => { WSV.ws = wsCur(); };
addEventListener('pagehide', () => { if (WSV.ws === wsCur()) wsv_save(WSV.ws); });
document.addEventListener('visibilitychange', () => { if (document.hidden && WSV.ws === wsCur()) wsv_save(WSV.ws); });
// the open task stays only when it belongs to the workspace now shown
const wsv_taskIn = (id, ws) => { const t = id && taskById(id); return !!t && !t.deleted_at && inWs(listById(t.list_id), ws); };
// closing it here takes no Back step (a phone's task entry would land on the old workspace's page): the entry is cleared
const wsv_close = () => { closeDetail(true); if (history.state?.detail) history.replaceState(null, '', location.hash); };
// the target workspace's own state of its areas (choices, open groups, folded folders) -- never its page
function wsv_restore(v, ws) {
  for (const k of WSV_KEYS) if (v.ls?.[k] == null) LS.del(k); else LS.set(k, v.ls[k]);
  if (S.nf) { S.nf.filter = LS.get('newsFilter', '') ? 'me' : ''; S.nf.kind = LS.get('newsKind', ''); S.nf.items = null; }
  if (S.jobs) { S.jobs.f = LS.get('jobsFilter', 'open'); S.jobs.items = null; }
  const shut = new Set(v.shut || []);
  for (const f of wsv_folders(ws)) if (foldClosed(f) !== shut.has(f)) foldSet(f, shut.has(f));
}
// 2.497.0 (#4048): where a switch to the workspace now set (ws) lands: the same page when it exists there; a single object that is
// not there -> the overview of the same area (a project: Projects); a list (folder, marked lists) not there -> the inbox; an area that does not exist
// there or is switched off there (module off, an area off for the workspace #3490, an organisation's part off #3560, a private
// module in an organisation #3950) -> Start. null = the page stays.
const WS_START = 'home';
const ws_listIn = (id, ws) => (l => !!l && !l.archived && inWs(l, ws))(listById(+id));
// the overview page of an object's area (the router's first word; old links like ev/5 or client/3 to their module)
const WS_ROOT = {ev: 'cal', client: 'clients', job: 'agents', note: 'notes'};
function ws_target(ws) {
  if (ws === 'all' || S.me?.kid) return null;  // "All" shows everything of the page; a kid has its own home
  const h = wsv_hashNow(), [a, b, c] = h.split('?')[0].split('/'), mod = S.route?.mod || 'tasks';
  const area = mod === 'tasks' || mod === 'home' ? null : typeof wsa_areaOfMod === 'function' ? wsa_areaOfMod(mod) : null;
  if (!modOn(mod) || o3a_hid(mod) || (area && WSA_AREAS.includes(area) && !wsa_areaOn(area, ws))) return WS_START;
  const mg = mod !== 'tasks' && mg_areaOf(mod);
  if (mg && nav_orgOff(mg[0], mod)) return WS_START;
  if (mod === 'tasks') {
    const k = String(S.route.key || '');
    if (k.startsWith('l:')) return ws_listIn(k.slice(2), ws) ? null : listById(+k.slice(2))?.kind === 'project' ? 'projects' : START_KEY;  // a project -> the overview of Projects, a list -> the inbox
    if (k.startsWith('lists:')) return k.slice(6).split(',').some(id => ws_listIn(id, ws)) ? null : START_KEY;
    if (k.startsWith('folder:')) { const f = k.slice(7); return S.lists.some(l => !l.is_inbox && !l.archived && fUnder(l.folder, f) && inWs(l, ws)) ? null : START_KEY; }
    return null;  // the inbox, Today, Projects, filters, tags, people: every workspace has them (they show its share)
  }
  if (!b) return null;  // an area's overview stays
  // what an object page may keep: its own workspace is known (a note's list, an agent, a table of a list), else its overview
  if (mod === 'notes') { const lid = a === 'note' ? (S.notes || []).find(n => n.id === +b)?.list_id : +b || null; return lid != null && ws_listIn(lid, ws) ? null : 'notes'; }
  if (mod === 'agents' && a === 'agents') { const ag = agentById(+b); return ag && wsAgentIn(ag, ws) ? null : 'agents'; }
  if (mod === 'sheets' && b === 'l') return ws_listIn(c, ws) ? null : 'sheets';
  if (mod === 'office') return c ? 'office/' + b : null;  // office/<tab> is a part of the office, office/<tab>/<id> one document
  if (mod === 'docs' && b === 'review') return null;  // a saved filter, no object
  if (mod === 'ablage' && /^aus-/.test(b)) return null;  // a collection
  if (mod === 'clients' && a === 'mailhub') return null;
  if (mod === 'msv') return null;  // a list on another server belongs to no workspace
  return WS_ROOT[a] || a;
}
// o.keep: the caller goes on to its own target (a link into the other workspace, News' or the office's "Switch"): the page
// only follows the filter (a list or private module not there -> the inbox, as before) and the caller then opens its target
async function wsSet(ws, o = {}) {
  if (!wsOptions().includes(ws)) ws = 'all';
  const from = wsCur();
  if (WSV.ws === from) wsv_save(from);  // 2.397.0 (#3404)
  if (typeof vm_leave === 'function') vm_leave();  // 2.497.0 (#4048): the place of the view left: no route may follow (the page stays)
  S.settings.workspace = ws; LS.set('ws', ws);
  // 2.455.0 (#3847): the phone's open drawer stays and shows the new workspace; route() must not close it either
  const hold = !!$('#side.open') && typeof SBM !== 'undefined';
  if (hold) SBM.keep = true; else closeSide?.();
  if (typeof pb_wsChanged === 'function') pb_wsChanged(true);  // 2.47.3 (#1360): the office follows once the server knows it
  p61b_wsRun(false);  // 2.66.1 (#1945)
  const to = wsCur(), kept = !o.keep && to !== 'all' ? (LS.get('wsView', {}) || {})[to] : null;
  WSV.ws = '';  // the page shown now belongs to the old workspace: route() must not keep it for the new one
  if (kept) wsv_restore(kept, to);  // its areas' own state, not its page
  // 2.497.0 (#4048): the open task (side panel, phone drawer, "All") stays when the new workspace shows it, else it closes
  if (S.sel && !wsv_taskIn(S.sel, to)) wsv_close();
  // 2.497.0 (#4048): the view entered by this switch does not reopen the task kept for it (viewmem.js, vm_after); only one open here stays
  if (typeof VM !== 'undefined') VM.noSel = !o.keep;
  let h = null;
  if (o.keep) {
    // 2.49.0 (#1770) / 2.484.0 (#3950): a list not in the new workspace or a private module's page -> Start, then the caller's target
    const ol = S.route?.mod === 'tasks' && String(S.route.key || '').startsWith('l:') ? listById(+S.route.key.slice(2)) : null;
    if ((ol && !inWs(ol, to)) || o3a_hid(S.route?.mod)) h = keyToHash(START_KEY);
  } else h = ws_target(to);
  if (h != null && h !== wsv_hashNow()) {
    // 2.498.0 (#3863): the menu's Back entry (backclose.js) would stay "ours" under the new hash: its history.back() took the switch back
    history.replaceState(history.state?.f8d ? null : history.state, '', '#' + h);  // no Back step into the old workspace's page
    await route();
  } else { render(); WSV.ws = to; }  // no route follows
  if (typeof VM !== 'undefined') VM.noSel = false;
  if (hold) SBM.keep = false;  // the next tap on an entry closes the drawer
  try { await api('PATCH', '/api/settings', {workspace: ws}); } catch { /* api() said it */ }
  if (typeof AB2 !== 'undefined') { AB2.org = null; ab2_reload(); }  // 2.96.0 D (#1941): absences follow the switch (server reads it)
  // 2.305 (bundle): the disposition too -- it followed only the state reload of the live update, which 2.280.0 (#3109) may brake for 8 s
  if (typeof DPV !== 'undefined') { DPV.org = null; if (S.route?.mod === 'workload' && WLV.tab === 'dispo') dp_reload(); else { DPV.data = null; DPV.free = null; } }
  if (typeof pb_wsChanged === 'function') pb_wsChanged(false);
  p61b_wsRun(true);  // 2.66.1 (#1945)
}
// 2.49.0 (#1770): a list of another workspace opened directly (link, search, notification): the filter follows it
function wsFollow(key) {
  const l = String(key || '').startsWith('l:') ? listById(+key.slice(2)) : null;
  if (!l || inWs(l)) return;
  const ws = wsOf(l);
  if (!wsOptions().includes(ws)) return;  // an organisation the person is not in (a list shared from outside): leave the filter
  const from = wsCur();
  S.settings.workspace = ws; LS.set('ws', ws);
  // 2.523.0 (#4189): the target's own state comes back like on a switch (wsSet); route() saved the old one just before (wsv_leave),
  // the page stays the link's target (wsv_restore is synchronous and does not touch the page)
  const kept = (LS.get('wsView', {}) || {})[ws];
  if (kept) wsv_restore(kept, ws);
  api('PATCH', '/api/settings', {workspace: ws}).catch(() => {});
  ws_autoNote(from);
}
// 2.484.0 (#3950): Kalmido switched the workspace by itself (a link to a private module or to a list of another workspace): a short
// note with "Back" (the workspace before; 2.497.0 (#4048): in the same area, Start when the area does not exist there). A deliberate switch says nothing
function ws_autoNote(from) {
  const to = wsCur();
  if (!S.booted || !from || from === to) return;
  setTimeout(() => toast(tr('Switched to {0}', wsName(to)), () => { wsSet(from); }, undefined, tr('Back')), 0);
}
// 2.49.0 (#1770): the fixed sign in a list's header: Private or the organisation, from the list's OWN org_id (not the
// filter), under "All" too; a click opens the workspace switch like the chip
function wsBadge(l) {
  if (!wsOn() || !l || l.is_inbox) return '';
  const ws = wsOf(l), nm = wsLabel(l.org_id);
  // 2.53.0 (#1474): an organisation's list: the sign in the organisation's colour (Private stays neutral)
  return `<button type="button" class="wsbadge tf5" data-act="ws-menu" data-ico="${ws === 'private' ? 'home' : 'brief'}" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', nm))}" aria-label="${esc(tr('Workspace: {0}', nm))}"${wsp_attr(ws) /* 2.57.0 B (#1807): my colour, Private too */}>${wsIcon(ws)}<span>${esc(nm)}</span></button>`;
}
// the switch in the sidebar (under the brand): one button naming the shown workspace (a long organisation name fits), the
// menu offers Private | <organisations> | All workspaces
// 2.161.2 A (#2607, variant B): the brand IS the switch: the bot icon + the word mark, big, on top; the shown workspace as
// a small line under it (dot + name), an arrow on the right. The menu adds Start and "Hide the sidebar" (wsMenu).
function wsBarHtml() {
  // 2.87.9 (#1933, P4): without an organisation the button stays and shows the private space (its menu has only that)
  const cur = wsOn() ? wsCur() : 'private';
  return `<button type="button" class="wsbar sbbrand ${cur === 'all' ? '' : 'on'}" data-act="ws-menu" aria-haspopup="menu" aria-label="${esc(APP_NAME + ' · ' + tr('Workspace') + ': ' + wsName(cur))}" title="${esc(tr('Workspace') + ' · ' + tr('Only this workspace is shown'))}"${wsp_attr(cur) /* 2.53.0 (#1474), 2.57.0 B (#1807) */}>${logoSvg(36)}<span class="sbbt">${wordSvg()}<span class="sbbsub">${cur === 'all' ? ic('brief', 's') : wsp_dot(cur) /* 2.138.0 B (#2161): colour dot (or the icon for "All") in front of the name */}<span class="wsn">${esc(wsName(cur))}</span></span></span>${ic('chev', 's') /* 2.138.0 B (#2161): name + arrow */}</button>`;
}
// 2.161.2 A (#2608): the brand's bot blinks now and then (every 20-60 s, by chance), never while something is typed, the
// page is hidden or a menu is open; no timer at all with reduced motion (the system setting; it can change while open)
let wsBlinkT = 0;
const wsBlinkCalm = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return true; } };
function wsBlinkPlan() {
  clearTimeout(wsBlinkT); wsBlinkT = 0;
  if (wsBlinkCalm()) return;
  wsBlinkT = setTimeout(() => {
    const b = $('#kbar .kbsw') || $('#side .sbbrand'), a = document.activeElement;  // 2.152.3 A (#2619): a computer: the head bar
    if (b && !document.hidden && !(a && (/INPUT|TEXTAREA|SELECT/.test(a.tagName) || a.isContentEditable)) && $('#pop')?.classList.contains('hidden') !== false) {
      b.classList.remove('blink'); void b.offsetWidth; b.classList.add('blink');
      setTimeout(() => b.classList.remove('blink'), 600);
    }
    wsBlinkPlan();
  }, 20000 + Math.random() * 40000);
}
try { matchMedia('(prefers-reduced-motion: reduce)').addEventListener?.('change', wsBlinkPlan); } catch { /* old engine */ }
wsBlinkPlan();
// the chip in the header while one workspace is shown (a click opens the switch as a menu)
function wsChip() {
  if (!wsOn() || wsCur() === 'all') return '';
  const cur = wsCur();
  return `<button type="button" class="wschip tf5" data-act="ws-menu" data-ico="${cur === 'private' ? 'home' : 'brief'}" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', wsName(cur)) + ' · ' + tr('Only this workspace is shown'))}" aria-label="${esc(tr('Workspace: {0}', wsName(cur)))}"${wsp_attr(cur) /* 2.53.0 (#1474), 2.57.0 B (#1807) */}>${wsIcon(cur)}<span>${esc(wsName(cur))}</span></button>`;
}
function wsMenu(anchor) {
  const cur = wsOn() ? wsCur() : 'private';
  const opts = wsOn() ? wsOptions() : ['private'];
  // 2.161.2 A (#2607): from the brand on top of the sidebar: a heading, then Start and hiding the sidebar (the drawer on a
  // phone closes; on a computer the sidebar folds away into the header's menu button, the same switch as side-fold)
  const brand = !!anchor?.closest?.('.sbbrand'), fold = !!LS.get('sideFold', false), drawer = isMobile() || !!$('#app')?.classList.contains('side-rail');
  const p = menu(anchor, [...(brand ? [{head: tr('Workspace')}] : []), ...opts.map(ws => ({label: wsName(ws), icon: ws === 'private' ? 'home' : ws === 'all' ? 'grid' : 'brief', on: ws === cur, fn: () => wsSet(ws)})),
    ...(brand ? ['-', {label: tr('Start'), icon: 'start', cls: 'wsm-home', fn: () => { if (isMobile()) closeSide(); go('home'); }},
      {label: !isMobile() && fold ? tr('Show the sidebar') : tr('Hide the sidebar'), icon: 'panel', cls: 'wsm-side', fn: () => isMobile() || (drawer && !fold) ? closeSide() : sideFold(!fold)}] : [])]);
  // 2.57.0 B (#1807): a colour dot in front of each workspace's name (my colour or its default; neutral = a ring)
  const off = brand ? 1 : 0;
  opts.forEach((ws, i) => { if (ws !== 'all') p?.querySelector(`[role="menuitem"][data-i="${i + off}"] .ml`)?.insertAdjacentHTML('beforebegin', wsp_dot(ws)); });
}
// the default workspace of a new list: the shown one; with "All" the one of the folder's lists, else the first organisation
// 2.364.0 D (#3033): proj = a new project: with "All" (and no folder rule) the workspace picked last for a new project, else Private
function wsDefaultOrg(folder = '', proj = false) {
  const cur = wsCur();
  if (cur === 'private') return null;
  if (cur.startsWith('org:')) return +cur.slice(4);
  const top = String(folder || '').split('/')[0];
  const fp = folderEff(folder); if ('org_id' in fp) return fp.org_id || null;  // 2.29.0 (#1030): the folder's workspace
  const ws = new Set(S.lists.filter(l => !l.is_inbox && folder && (l.folder === folder || String(l.folder || '').split('/')[0] === top)).map(l => l.org_id || null));
  if (ws.size === 1) return [...ws][0];
  if (proj) { const last = String(LS.get('wsLastProj', '') || ''); return (S.me?.workspaces || []).some(o => 'org:' + o.id === last) ? +last.slice(4) : null; }
  return (S.me?.workspaces || [])[0]?.id || null;
}
// 2.364.0 D (#3033): under "All workspaces" a private project carries a small house in the sidebar
const ws_prvMark = l => wsOn() && wsCur() === 'all' && !l.org_id && !l.is_inbox ? `<span class="shr wsprv" role="img" title="${esc(wsName('private'))}" aria-label="${esc(wsName('private'))}">${ic('home', 's')}</span>` : '';
// 2.580.0 (#4821): a task row of a mixed view (Today, Upcoming, filters, search, tags) under "All workspaces" names where the
// task comes from: the workspace's dot + "Workspace · Project" (phones <= 480 px: dot + the workspace's short letters, the rest in
// the title and for screen readers). Not inside an open list (no showList there), not with only one workspace (wsOn), not the inbox
// (it belongs to no workspace). For a private project this is the row's sign of Private: ws_prvMark stays the sidebar's only.
const ws_isOrigin = l => !!l && !l.is_inbox && wsOn() && wsCur() === 'all';
const ws_abbr = ws => { const w = wsName(ws).trim().split(/\s+/).filter(Boolean).map(x => Array.from(x));
  return (w.length > 1 ? w[0][0] + w[1][0] : (w[0] || []).slice(0, 2).join('')).toUpperCase(); };
function ws_originHtml(l, lst, cls) {
  const ws = wsOf(l), nm = wsName(ws);
  return `<span class="${cls} wso" title="${esc(nm + ' · ' + lst)}"><span class="sr">${esc(tr('Workspace: {0}', nm) + ', ' + tr('Project') + ': ' + lst)}</span>`
    + `<span class="wsov" aria-hidden="true">${wsp_dot(ws)}<span class="wsows">${esc(nm)}</span><span class="wsoab">${esc(ws_abbr(ws))}</span><span class="wsosep">·</span>${licMark(l, 'lsm')}<span class="wsol">${esc(lst)}</span></span></span>`;
}
// the <select> of a list's workspace (list dialog); only when the person has an organisation
function wsSelectHtml(id, cur, dis = '') {
  if (!wsOn()) return '';
  return `<select id="${id}" ${dis}>${wsOptions().filter(w => w !== 'all').map(ws => `<option value="${ws === 'private' ? '' : ws.slice(4)}" ${(cur ? 'org:' + cur : 'private') === ws ? 'selected' : ''}>${esc(wsName(ws))}</option>`).join('')}</select>`;
}
// 2.30.0 (#1036): "New calendar / address book": the name and (with an organisation) its workspace -> {name, org_id} or null
async function wsAskNew(title) {
  let org = wsDefaultOrg();
  const p = askPrompt(title, '', {input: {max: 100, placeholder: tr('Name')}, ok: tr('Create'),
    html: wsOn() ? `<label class="wsnew"><span>${esc(tr('Workspace'))}</span>${wsSelectHtml('ws-new', org)}</label>` : ''});
  const sel = $('#ws-new');
  if (sel) sel.addEventListener('change', () => { org = sel.value ? +sel.value : null; });
  const n = await p;
  return n && n.trim() ? {name: n.trim(), org_id: org} : null;
}
// the menu "Workspace" of an own calendar / address book: Private | <organisations>, the current one ticked; fn(org_id)
function wsMoveMenu(anchor, cur, fn) {
  menu(anchor, wsOptions().filter(w => w !== 'all').map(ws => ({label: wsName(ws), icon: ws === 'private' ? 'home' : 'brief',
    on: (cur ? 'org:' + cur : 'private') === ws, fn: () => fn(ws === 'private' ? null : +ws.slice(4))})));
}
// 2.28.0 (#985): a small robot on an agent's picture wherever people appear; a tooltip for everyone, the text for screen readers
const botBadge = () => `<i class="abot-b" title="${esc(tr('Agent'))}" role="img" aria-label="${esc(tr('Agent'))}">${ic('bot', 's')}</i>`;
// 2.28.0 (#987): the bell counts only what PEOPLE send me: mentions, assignments, replies, decisions + unread direct messages
const bellCount = () => (S.news?.unread_me || 0) + (S.team?.dm_unread || 0) + (typeof msvvUnread === 'function' ? msvvUnread() : 0);  // 2.73.0 C (#661): + other servers
const newsForMe = it => !!it.to_me;
const newsInWs = it => wsCur() === 'all' || !it.list_id || inWs(listById(it.list_id));
// 2.87.9 (#1940): every importer asks before it starts where the data goes, in words: ws = 'private' | 'org:<id>' (the
// space the import files into), what = the things, translated and counted where known ("182 documents"), place = the
// container inside it (a list, a calendar, an address book), privOk = the importer can go into the private space instead
// ("Rather into private", only with an organisation as the target). Resolves 'same' | 'private' | null (cancelled).
// 2.144.5 B (#2002): orgAlt = 'org:<id>' offered the other way round when the target is the private space ("Rather into
// <organisation>", resolves 'org').
function importTargetConfirm({what, ws = 'private', place = '', privOk = false, orgAlt = '', check = null}) {  // 2.306.0 C (#2889): check = {label, hint, out}: a tick box, its state lands in out.on (default on)
  const org = String(ws || '').startsWith('org:'), name = org ? wsName(ws) : '';
  let priv = false;
  const body = org
    ? (place ? tr('Import {0} into “{1}” of the organisation {2}. Members of the organisation with access to it can see them.', what, place, name)
      : tr('Import {0} into the organisation {1}. Members of the organisation with access to it can see them.', what, name))
    : (place ? tr('Import {0} into “{1}” in your private workspace.', what, place) : tr('Import {0} into your private workspace.', what));
  return askDialog({title: org ? tr('Import into the organisation {0}?', name) : tr('Import into your private workspace?'), body, ok: tr('Import'),
    after: md => {
      md.classList.add('itc-dlg');
      if (check) {
        check.out.on = true;
        $('.cdlg-b', md).insertAdjacentHTML('afterend', `<label class="row" style="gap:8px;align-items:flex-start;margin:10px 0"><input type="checkbox" data-itc="check" checked><span>${esc(check.label)}<br><small class="muted">${esc(check.hint)}</small></span></label>`);
        $('[data-itc="check"]', md).addEventListener('change', e => { check.out.on = e.target.checked; });
      }
      if (!org && orgAlt) {  // 2.144.5 B (#2002)
        $('.foot', md).insertAdjacentHTML('afterbegin', `<button type="button" class="btn" data-itc="org">${wsIcon(orgAlt)} ${esc(tr('Rather into {0}', wsName(orgAlt)))}</button>`);
        $('button[data-itc]', md).addEventListener('click', () => { priv = 'org'; $('form', md).requestSubmit(); });
        return;
      }
      if (!org || !privOk) return;
      const f = $('.foot', md);
      f.insertAdjacentHTML('afterbegin', `<button type="button" class="btn" data-itc="private">${ic('home', 's')} ${esc(tr('Rather into private'))}</button>`);
      $('button[data-itc]', md).addEventListener('click', () => { priv = true; $('form', md).requestSubmit(); });
    }}).then(ok => ok ? (priv === 'org' ? 'org' : priv ? 'private' : 'same') : null);
}
