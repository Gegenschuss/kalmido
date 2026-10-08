// 2.28.0 (#935): workspaces -- "Private" and the organisations a person belongs to. Every list has one (list.org_id, null =
// private); the sidebar's switch (setting "workspace": all | private | org:<id>, followed on every device) shows the lists,
// tasks, News, agents and team chats of ONE workspace, "All" shows everything. The inbox is always there. The server keeps
// the boundary between people (an organisation's list is shared only inside it, agents join only lists of their workspace);
// this module only decides what the app shows.
// 2.28.0 (#985): the bot badge on an agent's picture (botBadge), (#987) what counts as "For you" at the bell (bellCount).
const wsOn = () => !!S.workspaces && !!(S.me?.workspaces || []).length;
const wsCur = () => { const v = S.settings?.workspace || 'all'; return wsOn() && (v === 'private' || (v.startsWith('org:') && (S.me.workspaces || []).some(w => 'org:' + w.id === v))) ? v : 'all'; };
const wsOf = l => !l || !l.org_id ? 'private' : 'org:' + l.org_id;
const inWs = (l, ws = wsCur()) => ws === 'all' || !l || !!l.is_inbox || wsOf(l) === ws;
// a task of a list outside the shown workspace is hidden everywhere except in that list itself (like an archived list's)
const wsHidden = t => wsCur() !== 'all' && !!t && !inWs(listById(t.list_id)) && !(S.route.mod === 'tasks' && S.route.key === 'l:' + t.list_id);
const wsOrg = id => (S.me?.workspaces || []).find(w => w.id === +id);
const wsName = ws => ws === 'all' ? tr('All workspaces') : ws === 'private' ? tr('Private|workspace') : (wsOrg(ws.slice(4))?.name || tr('Organisation'));
const wsIcon = ws => ws === 'private' ? ic('home', 's') : ws === 'all' ? ic('grid', 's') : (wsOrg(ws.slice(4))?.icon ? `<span class="wsemo" aria-hidden="true">${esc(wsOrg(ws.slice(4)).icon)}</span>` : ic('brief', 's'));
const wsOptions = () => ['private', ...(S.me?.workspaces || []).map(w => 'org:' + w.id), 'all'];
const wsAgentIn = (a, ws = wsCur()) => ws === 'all' || !a || (ws === 'private' ? !a.org_id : 'org:' + a.org_id === ws);
const wsLabel = (org_id) => org_id ? (wsOrg(org_id)?.name || tr('Organisation')) : tr('Private|workspace');
async function wsSet(ws) {
  if (!wsOptions().includes(ws)) ws = 'all';
  S.settings.workspace = ws; LS.set('ws', ws);
  closeSide?.();
  render();
  try { await api('PATCH', '/api/settings', {workspace: ws}); } catch { /* api() said it */ }
}
// the switch in the sidebar (under the brand): one button naming the shown workspace (a long organisation name fits), the
// menu offers Private | <organisations> | All workspaces
function wsBarHtml() {
  if (!wsOn()) return '';
  const cur = wsCur();
  return `<button type="button" class="wsbar ${cur === 'all' ? '' : 'on'}" data-act="ws-menu" aria-haspopup="menu" aria-label="${esc(tr('Workspace') + ': ' + wsName(cur))}" title="${esc(tr('Workspace') + ' · ' + tr('Only this workspace is shown'))}">${wsIcon(cur)}<span class="wsn">${esc(wsName(cur))}</span>${ic('chev', 's')}</button>`;
}
// the chip in the header while one workspace is shown (a click opens the switch as a menu)
function wsChip() {
  if (!wsOn() || wsCur() === 'all') return '';
  const cur = wsCur();
  return `<button type="button" class="wschip" data-act="ws-menu" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', wsName(cur)) + ' · ' + tr('Only this workspace is shown'))}" aria-label="${esc(tr('Workspace: {0}', wsName(cur)))}">${wsIcon(cur)}<span>${esc(wsName(cur))}</span></button>`;
}
function wsMenu(anchor) {
  const cur = wsCur();
  menu(anchor, wsOptions().map(ws => ({label: wsName(ws), icon: ws === 'private' ? 'home' : ws === 'all' ? 'grid' : 'brief', on: ws === cur, fn: () => wsSet(ws)})));
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
// 2.28.0 (#985): a small robot on an agent's picture wherever people appear; a tooltip for everyone, the text for screen readers
const botBadge = () => `<i class="abot-b" title="${esc(tr('Agent'))}" role="img" aria-label="${esc(tr('Agent'))}">${ic('bot', 's')}</i>`;
// 2.28.0 (#987): the bell counts only what PEOPLE send me: mentions, assignments, replies, decisions + unread direct messages
const bellCount = () => (S.news?.unread_me || 0) + (S.team?.dm_unread || 0);
const newsForMe = it => !!it.to_me;
const newsInWs = it => wsCur() === 'all' || !it.list_id || inWs(listById(it.list_id));
