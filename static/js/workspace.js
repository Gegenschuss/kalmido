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
async function wsSet(ws) {
  if (!wsOptions().includes(ws)) ws = 'all';
  S.settings.workspace = ws; LS.set('ws', ws);
  closeSide?.();
  if (typeof pb_wsChanged === 'function') pb_wsChanged(true);  // 2.47.3 (#1360): the office follows once the server knows it
  p61b_wsRun(false);  // 2.66.1 (#1945)
  // 2.49.0 (#1770): the open list does not stay when it is not part of the new workspace -> that workspace's inbox
  const ol = S.route?.mod === 'tasks' && String(S.route.key || '').startsWith('l:') ? listById(+S.route.key.slice(2)) : null;
  if (ol && !inWs(ol, wsCur())) go(keyToHash(START_KEY)); else render();
  try { await api('PATCH', '/api/settings', {workspace: ws}); } catch { /* api() said it */ }
  if (typeof AB2 !== 'undefined') { AB2.org = null; ab2_reload(); }  // 2.96.0 D (#1941): absences follow the switch (server reads it)
  if (typeof pb_wsChanged === 'function') pb_wsChanged(false);
  p61b_wsRun(true);  // 2.66.1 (#1945)
}
// 2.49.0 (#1770): a list of another workspace opened directly (link, search, notification): the filter follows it
function wsFollow(key) {
  const l = String(key || '').startsWith('l:') ? listById(+key.slice(2)) : null;
  if (!l || inWs(l)) return;
  const ws = wsOf(l);
  if (!wsOptions().includes(ws)) return;  // an organisation the person is not in (a list shared from outside): leave the filter
  S.settings.workspace = ws; LS.set('ws', ws);
  api('PATCH', '/api/settings', {workspace: ws}).catch(() => {});
}
// 2.49.0 (#1770): the fixed sign in a list's header: Private or the organisation, from the list's OWN org_id (not the
// filter), under "All" too; a click opens the workspace switch like the chip
function wsBadge(l) {
  if (!wsOn() || !l || l.is_inbox) return '';
  const ws = wsOf(l), nm = wsLabel(l.org_id);
  // 2.53.0 (#1474): an organisation's list: the sign in the organisation's colour (Private stays neutral)
  return `<button type="button" class="wsbadge" data-act="ws-menu" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', nm))}" aria-label="${esc(tr('Workspace: {0}', nm))}"${wsp_attr(ws) /* 2.57.0 B (#1807): my colour, Private too */}>${wsIcon(ws)}<span>${esc(nm)}</span></button>`;
}
// the switch in the sidebar (under the brand): one button naming the shown workspace (a long organisation name fits), the
// menu offers Private | <organisations> | All workspaces
function wsBarHtml() {
  // 2.87.9 (#1933, P4): without an organisation the button stays and shows the private space (its menu has only that)
  const cur = wsOn() ? wsCur() : 'private';
  return `<button type="button" class="wsbar ${cur === 'all' ? '' : 'on'}" data-act="ws-menu" aria-haspopup="menu" aria-label="${esc(tr('Workspace') + ': ' + wsName(cur))}" title="${esc(tr('Workspace') + ' · ' + tr('Only this workspace is shown'))}"${wsp_attr(cur) /* 2.53.0 (#1474), 2.57.0 B (#1807) */}>${cur === 'all' ? ic('brief', 's') : wsp_dot(cur) /* 2.138.0 B (#2161): colour dot (or the icon for "All") in front of the name */}<span class="wsn">${esc(wsName(cur))}</span>${ic('chev', 's') /* 2.138.0 B (#2161): name + arrow */}</button>`;
}
// the chip in the header while one workspace is shown (a click opens the switch as a menu)
function wsChip() {
  if (!wsOn() || wsCur() === 'all') return '';
  const cur = wsCur();
  return `<button type="button" class="wschip" data-act="ws-menu" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', wsName(cur)) + ' · ' + tr('Only this workspace is shown'))}" aria-label="${esc(tr('Workspace: {0}', wsName(cur)))}"${wsp_attr(cur) /* 2.53.0 (#1474), 2.57.0 B (#1807) */}>${wsIcon(cur)}<span>${esc(wsName(cur))}</span></button>`;
}
function wsMenu(anchor) {
  const cur = wsOn() ? wsCur() : 'private';
  const opts = wsOn() ? wsOptions() : ['private'];
  const p = menu(anchor, opts.map(ws => ({label: wsName(ws), icon: ws === 'private' ? 'home' : ws === 'all' ? 'grid' : 'brief', on: ws === cur, fn: () => wsSet(ws)})));
  // 2.57.0 B (#1807): a colour dot in front of each workspace's name (my colour or its default; neutral = a ring)
  opts.forEach((ws, i) => { if (ws !== 'all') p?.querySelector(`[role="menuitem"][data-i="${i}"] .ml`)?.insertAdjacentHTML('beforebegin', wsp_dot(ws)); });
}
// the default workspace of a new list: the shown one; with "All" the one of the folder's lists, else the first organisation
function wsDefaultOrg(folder = '') {
  const cur = wsCur();
  if (cur === 'private') return null;
  if (cur.startsWith('org:')) return +cur.slice(4);
  const top = String(folder || '').split('/')[0];
  const fp = folderEff(folder); if ('org_id' in fp) return fp.org_id || null;  // 2.29.0 (#1030): the folder's workspace
  const ws = new Set(S.lists.filter(l => !l.is_inbox && folder && (l.folder === folder || String(l.folder || '').split('/')[0] === top)).map(l => l.org_id || null));
  if (ws.size === 1) return [...ws][0];
  return (S.me?.workspaces || [])[0]?.id || null;
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
function importTargetConfirm({what, ws = 'private', place = '', privOk = false}) {
  const org = String(ws || '').startsWith('org:'), name = org ? wsName(ws) : '';
  let priv = false;
  const body = org
    ? (place ? tr('Import {0} into “{1}” of the organisation {2}. Members of the organisation with access to it can see them.', what, place, name)
      : tr('Import {0} into the organisation {1}. Members of the organisation with access to it can see them.', what, name))
    : (place ? tr('Import {0} into “{1}” in your private space.', what, place) : tr('Import {0} into your private space.', what));
  return askDialog({title: org ? tr('Import into the organisation {0}?', name) : tr('Import into your private space?'), body, ok: tr('Import'),
    after: md => {
      md.classList.add('itc-dlg');
      if (!org || !privOk) return;
      const f = $('.foot', md);
      f.insertAdjacentHTML('afterbegin', `<button type="button" class="btn" data-itc="private">${ic('home', 's')} ${esc(tr('Rather into private'))}</button>`);
      $('[data-itc]', md).addEventListener('click', () => { priv = true; $('form', md).requestSubmit(); });
    }}).then(ok => ok ? (priv ? 'private' : 'same') : null);
}
