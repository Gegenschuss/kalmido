// 2.46.6: what the agent views show about an agent's lists and setup (#1680 #1708 #1709 #1716).

// ---- 2.46.6 (#1680): personal agents and the switch "Members may see and use the agent". Only its owner can address a
// personal agent (agent_usable), whatever the switch says; the switch is for team agents. The hint says so at the switch.
// The personal agents in list l: [{name, mine, owner}] (members carry agent_owner from /api/state)
const av_personal = l => listPeople(l).filter(p => p.agent_owner || agentById(p.user_id)?.owner_id).map(p => {
  const a = agentById(p.user_id), mine = !!a && a.owner_id === S.me?.id;
  return {name: a?.name || p.name, mine, owner: mine ? '' : p.agent_owner || ''};
});
const av_folderPersonal = f => (S.lists || []).filter(l => !l.archived && fUnder(l.folder, f)).flatMap(av_personal);
function av_personalHint(ps) {
  const x = ps[0]; if (!x) return '';
  return x.mine ? tr('{0} is your personal agent: only you can address it, also with this switch on. It runs on your computer and uses your quota. The switch is for team agents.', x.name)
    : tr('{0} is the personal agent of {1}: only {1} can address it, also with this switch on. It runs on their computer and uses their quota. The switch is for team agents.', x.name, x.owner || tr('someone else'));
}

// ---- 2.46.6 (#1709): right after creating an agent: "Set up on a computer now?" -- Set up (the one-command setup, #1517) /
// Later / the token for an own setup. The token comes back only this once: it lives in this dialog until it is closed,
// nothing stores it. base = /api/my/agents/<id> (own agent) or /api/admin/agents/<id> (an admin's team agent).
function av_setupOffer(a, base, token) {
  const md = modal(`<h3>${esc(tr('Agent created. Set it up on a computer now?'))}</h3>
    <div class="shint keep">${esc(tr('One command installs {0} on your Mac, Windows PC or Linux computer and starts it at every login; the command fetches its own token.', a.name))}</div>
    <div class="avtok" id="av-tok" hidden></div>
    <div class="foot"><button type="button" class="linkbtn" data-m="av-tok">${tr('Show the token for an own setup')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Later')}</button><button class="btn pri" data-m="av-setup">${ic('download', 's')} ${tr('Set up')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'av-setup') { md.remove(); ains_setupModal(a, base); return; }
    if (b.dataset.m === 'av-copy') { try { await navigator.clipboard.writeText(token); toast(tr('Copied')); } catch { $('#av-tokv', md)?.select(); } return; }
    if (b.dataset.m === 'av-tok') {
      b.hidden = true;
      const box = $('#av-tok', md); box.hidden = false;
      box.innerHTML = `<div class="shint keep">${tr('Copy it now into the agent’s configuration: it is shown only this once.')}</div>
        <div class="row icalrow"><input id="av-tokv" readonly value="${esc(token || '')}" aria-label="${esc(tr('API token of {0}', a.name))}" spellcheck="false"><button class="btn sm" data-m="av-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>`;
    }
  });
  setTimeout(() => $('[data-m="av-setup"]', md)?.focus(), 50);
  return md;
}
// the setup button of an agent's row: with its text while no computer ever connected (contact_age null), else the icon
const av_setupBtn = a => a.contact_age == null && !a.webhook
  ? `<button class="btn sm avsetup" data-myag-act="setup" aria-label="${esc(tr('Set up {0} on a computer', a.name))}">${ic('download', 's')} ${tr('Set up')}</button>`
  : `<button class="iconbtn" data-myag-act="setup" title="${esc(tr('Set up on a computer'))}" aria-label="${esc(tr('Set up {0} on a computer', a.name))}">${ic('download', 's')}</button>`;

// ---- 2.46.6 (#1708): the section "Lists" on an agent's card in the Agents view: every list the agent is in that I see (from
// /api/state, nothing new from the server), with folder, who may address it there and whether it listens in; a tap opens
// the list's settings. A personal agent: a line on top (only its owner uses it, see #1680).
S.av_open = S.av_open || {};
const av_isAgent = (l, p) => p.agent || !!agentById(p.user_id) || (p.user_id === l.owner_id && !!agentById(l.owner_id));
const av_people = l => listPeople(l).filter(p => !av_isAgent(l, p)).length;
// 2.58.0 (#1761): within its list limit (list_ids only reaches the people who manage it; [] / missing = all its lists)
const av_agentLists = a => sideOrder().filter(l => !l.archived && !l.is_inbox && listPeople(l).some(p => p.user_id === a.id)
  && !(a.list_ids?.length && !a.list_ids.includes(l.id)));
function av_whoTxt(a, l) {
  const n = av_people(l);
  if (a.owner_id) return a.owner_id === S.me?.id ? tr('only you') + (n > 1 ? ' · ' + trn('{0} other person sees what it does', '{0} other people see what it does', n - 1) : '') : tr('only its owner');
  return l.agent_members || l.owner_id === a.id ? tr('all members ({0})', trn('{0} person', '{0} people', n))
    : l.role === 'owner' || l.owner_id === S.me?.id ? tr('only you and list admins') : tr('only the list owner and list admins');
}
function av_listsHtml(a) {
  const ls = av_agentLists(a);
  const top = a.owner_id === S.me?.id ? `<div class="shint keep avtop">${esc(tr('Only you use it.'))}${ls.some(l => av_people(l) > 1) ? ' ' + esc(tr('Others in shared lists see what it does, but cannot address it.')) : ''}</div>`
    : !a.owner_id && ls.some(l => l.agent_members || l.owner_id === a.id) ? `<div class="shint keep avtop">${esc(tr('Others can use it in: {0}', ls.filter(l => l.agent_members || l.owner_id === a.id).map(lname).join(', ')))}</div>` : '';
  const row = l => `<button type="button" class="avlrow" data-avlist="${l.id}" aria-label="${esc(tr('Settings of {0}', lname(l)))}"><span class="avln"><b>${esc(lname(l))}</b>${l.folder ? `<span class="muted"> · ${esc(fDisp(l.folder))}</span>` : ''}</span>
    <small class="muted">${esc([av_whoTxt(a, l), (l.listen_agent_ids || []).includes(a.id) ? tr('listens in') : tr('only via @')].join(' · '))}</small></button>`;
  return `<details class="aglists" data-avag="${a.id}" ${S.av_open[a.id] ? 'open' : ''}><summary>${ic('list', 's')} ${esc(tr('Lists'))} <span class="muted">${ls.length}</span></summary>
    ${top}${ls.length ? `<div class="avls">${ls.map(row).join('')}</div>` : `<div class="muted mhint">${esc(tr('Not in any list you see yet. Share a list with it (list dialog > Sharing).'))}</div>`}</details>`;
}
document.addEventListener('toggle', e => { const d = e.target; if (d.matches?.('details[data-avag]')) S.av_open[d.dataset.avag] = d.open; }, true);
document.addEventListener('click', e => { const b = e.target.closest?.('[data-avlist]'); if (b) { e.preventDefault(); listModal(+b.dataset.avlist); } });

// ---- 2.46.6 (#1708): the workspace of my personal agent in its row (Settings > Agents > Set up): shown and changed in a menu
// (PATCH /api/my/agents/<id> org_id; the server refuses a workspace its lists do not fit), with Undo
const av_wsBtn = a => wsOn() ? `<button type="button" class="linkbtn avws" data-myag-act="ws" aria-haspopup="menu" title="${esc(tr('Workspace: {0}', wsLabel(a.org_id)))}" aria-label="${esc(tr('Workspace: {0}', wsLabel(a.org_id)))}">${wsIcon(a.org_id ? 'org:' + a.org_id : 'private')}<span>${esc(wsLabel(a.org_id))}</span></button>` : '';
function av_wsMenu(anchor, a, redraw) {
  const set = async (org, undo) => {
    try { await api('PATCH', `/api/my/agents/${a.id}`, {org_id: org}); } catch { return; }
    await load(); render(); redraw();
    toast(tr('{0} now works in {1}', a.name, wsLabel(org)), undo ? () => set(a.org_id ?? null, false) : undefined);
  };
  menu(anchor, wsOptions().filter(w => w !== 'all').map(ws => { const org = ws === 'private' ? null : +ws.slice(4);
    return {label: wsName(ws), icon: org ? 'brief' : 'home', ...(org === (a.org_id ?? null) ? {sub: tr('current')} : {}), fn: () => { if (org !== (a.org_id ?? null)) set(org, true); }}; }));
}

// ---- 2.46.6 (#1716): "Which agent when?" -- a short, folded help where an agent is created (Settings > Agents > Set up and
// the admin's dialog for a new agent)
const av_whichHtml = () => `<details class="avwhich"><summary>${ic('help', 's')} ${esc(tr('Which agent when?'))}</summary><ul class="shint keep">
  <li>${esc(tr('Personal: it runs on your computer, with your Claude access and quota, in your working folder, and only you give it orders. It can still work in the workspace of an organisation.'))}</li>
  <li>${esc(tr('Team agent: colleagues give it orders themselves; it runs on a shared computer that is always on, with an account of the organisation. Its rules name who may give orders.'))}</li>
  <li>${esc(tr('Fewer people giving orders means less risk. A personal agent is gone while your computer is off.'))}</li>
  <li>${esc(tr('Switching later needs no new setup: an admin changes “Belongs to” to team or person. Lists and history stay; adjust the rules in its CLAUDE.md.'))}</li></ul></details>`;
