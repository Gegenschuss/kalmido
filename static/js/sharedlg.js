// ---- 2.41.0 (#1420 / #1423): the Share dialog of a folder, built like the one of a list (shareModal, dialogs.js): a ✕ in the
// head, People (the owner first, roles, "Add", by e-mail address, what the roles may do), Groups, Agents (several per folder,
// the first is the default of its lists, "listens in" per agent), Notifications for members, Public link, Owner, and the
// footer "Folder settings…" | "Done". What a folder cannot do like a list stays visible, greyed out, with the reason.
// The agent switches (members may use it, follows up, tidying) stay in the folder settings; they link here and back.
const FSH_HID = {grp: 'fsh-grp-h', ag: 'fsh-ag-h', pub: 'fsh-pub-h', own: 'fsh-own-h', ntf: 'fp-ntf-h'};
const fshId = k => k === 'ntf' ? 'fp' : 'fsh';  // the notifications part keeps the ids of the former "Share folder" dialog (fp-sec-ntf)
const fshSec = (k, title, inner, open = false) => `<details class="shsec" id="${fshId(k)}-sec-${k}" ${open ? 'open' : ''}><summary><h4 id="${FSH_HID[k]}">${title}</h4><span class="shsecst muted" id="${fshId(k)}-st-${k}"></span>${ic('chev', 's shchev')}</summary>${inner}</details>`;
const fshGrey = (txt, why) => `<div class="fshgrey" aria-disabled="true"><span>${esc(txt)}</span><small class="muted">${esc(why)}</small></div>`;
function folderShareModal(f, opt = {}) {
  if (!collab()) return null;
  const own = folderLists(f).some(l => isOwner(l)) || !folderLists(f).length;
  const md = modal(`<div class="lhdr"><h3>${esc(tr('Share folder “{0}”', fDisp(f)))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="shint lhint keep">${tr('Every list in this folder is shared now, and every list you add to it later. With them the lists land in a folder of the same name; they can move them freely.')}</div>
    <h4 id="fsh-people-h">${tr('People')}</h4><div class="members fpl" id="fsh-members" aria-labelledby="fsh-people-h"><div class="muted mhint">${tr('Loading…')}</div></div>
    ${S.peopleVis === 'contacts' ? `<div class="row shmail"><input id="fsh-email" type="email" autocomplete="off" placeholder="${esc(tr('Share by e-mail address'))}" aria-label="${esc(tr('Share by e-mail address'))}"><button type="button" class="btn sm" data-m="fsh-mail">${ic('send', 's')} ${tr('Add')}</button></div>` : ''}
    <details class="rolehelp sdet"><summary>${tr('What the roles may do')}</summary>${ROLES.map(([, n, h]) => `<div><b>${tr(n)}</b> <span class="muted">${tr(h)}</span></div>`).join('')}</details>
    ${(S.groups || []).length ? fshSec('grp', tr('Groups'), `<div class="members" id="fsh-grp"><div class="muted mhint">${tr('Loading…')}</div></div>`, opt.focus === 'grp') : ''}
    ${agentsOn() ? fshSec('ag', tr('Agents'), `<div class="shint lhint keep">${tr('An agent sees exactly the lists shared with it, nothing else. Stopping the sharing ends its access at once.')} ${tr('A list has at most one agent: the lists get the first one (the default), the others can be chosen per list in its Share dialog.')}</div><div id="fsh-ag"><div class="muted mhint">${tr('Loading…')}</div></div>
      ${fshGrey(tr('Members may see and use the agent') + ' · ' + tr('Agent follows up') + ' · ' + tr('Agent may tidy up entries'), tr('For a folder in the folder settings (defaults for its lists).'))}
      <div class="row"><span class="spacer"></span><button type="button" class="linkbtn" data-m="fsh-props">${ic('sliders', 's')} ${tr('Folder settings…')}</button></div>`, opt.focus === 'agents') : ''}
    ${fshSec('ntf', tr('Notifications for members'), `<div id="fp-ntf"><div class="muted mhint">${tr('Loading…')}</div></div>`, opt.focus === 'ntf')}
    ${S.publicLinks ? fshSec('pub', tr('Public link'), `<div id="fsh-pub"><div class="muted mhint">${tr('Loading…')}</div></div>`) : ''}
    ${fshSec('own', tr('Owner'), `<div id="fsh-own"></div>`)}
    <div class="foot"><button class="btn" data-m="fsh-props">${ic('sliders', 's')} ${tr('Folder settings…')}</button><span class="spacer"></span><button class="btn pri" data-m="close">${opt.back ? ic('back', 's') + ' ' + tr('Back') : tr('Done')}</button></div>`);
  md.classList.add('shmodal', 'fshmodal');
  md.dataset.folder = f;
  let users = null, have = [], ags = null;
  const st = (k, t) => { const e = $(`#${fshId(k)}-st-${k}`, md); if (e) e.textContent = t || ''; };
  const roleSel = (attr, cur, lab) => `<select ${attr} aria-label="${esc(lab || tr('Role'))}">${ROLES.map(([v, n, h]) => `<option value="${v}" title="${esc(tr(h))}" ${v === cur ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>`;
  const fws = () => { const e = folderEff(f); if ('org_id' in e) return e.org_id || null; const m = folderLists(f).find(l => isOwner(l)); return m ? m.org_id || null : wsDefaultOrg(f); };  // the folder's workspace, else its lists'
  const agFits = u => !wsOn() || (u.org_id || null) === fws();  // the agents of the folder's workspace, as in a list (agFits)
  const drawPeople = () => {
    const box = $('#fsh-members', md); if (!box) return;
    const nm = p => p.name || users?.find(u => u.id === p.user_id)?.display_name || '?';
    const cand = (users || []).filter(u => !u.agent && u.id !== S.me?.id && !have.some(p => p.user_id === u.id));
    box.innerHTML = `<div class="mrow fshowner">${av(S.me?.id, S.me?.display_name || '')}<span class="n">${esc(S.me?.display_name || '')} ${tr('(me)')}</span><span class="muted">${tr('Owner')}</span></div>`
      + have.map(p => `<div class="mrow" data-uid="${p.user_id}">${avBtn(p.user_id, nm(p))}<span class="n"><span class="fpn">${esc(nm(p))}</span> <small class="muted">${tr('new lists too')}</small></span>${roleSel(`data-fprole="${p.user_id}"`, p.role, tr('Role of {0}', nm(p)))}<button class="iconbtn" data-rm="${p.user_id}" title="${esc(tr('Stop sharing'))}" aria-label="${esc(tr('Stop sharing with {0}', nm(p)))}">${ic('x', 's')}</button></div>`).join('')
      + (users === null ? `<div class="muted mhint">${tr('Loading…')}</div>` : cand.length ? `<div class="mrow madd"><select id="fp-user" aria-label="${esc(tr('Invite'))}"><option value="">${tr('Share with …')}</option>${cand.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select>${roleSel('id="fp-role"', 'edit')}<button class="btn sm" data-m="add">${ic('plus', 's')} ${tr('Add')}</button></div>`
        : `<div class="muted mhint">${(users || []).filter(u => !u.agent).length > 1 ? tr('Shared with everyone') : tr('No other users yet. An admin can add them in the settings.')}</div>`);
  };
  const drawGroups = async () => {
    const box = $('#fsh-grp', md); if (!box) return;
    let gs; try { gs = (await calReq('GET', '/api/folders/groups?folder=' + encodeURIComponent(f))).groups; } catch { box.innerHTML = ''; return; }
    if (!md.isConnected) return;
    const cand = (S.groups || []).filter(g => !gs.some(x => x.group_id === g.id));
    box.innerHTML = gs.map(x => `<div class="mrow">${fg_gav(x.group_id)}<span class="n">${esc(x.name)}</span>${roleSel(`data-fgrole="${x.group_id}"`, x.role, tr('Role of the group {0}', x.name))}<button class="iconbtn" data-fgrm="${x.group_id}" title="${esc(tr('Stop sharing with the group'))}" aria-label="${esc(tr('Stop sharing with the group {0}', x.name))}">${ic('x', 's')}</button></div>`).join('')
      + (cand.length ? `<div class="mrow madd"><select id="fg-add" aria-label="${esc(tr('Share with a group'))}"><option value="">${tr('Share with a group …')}</option>${cand.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join('')}</select>${roleSel('id="fg-role"', 'edit')}<button class="btn sm" data-m="fg-add">${ic('plus', 's')} ${tr('Add')}</button></div>` : '')
      || `<div class="muted mhint">${tr('No groups yet')}</div>`;
    st('grp', gs.length ? trn('{0} group', '{0} groups', gs.length) : '');
  };
  const drawAgents = () => {
    const box = $('#fsh-ag', md); if (!box || !ags) return;
    const all = (users || []).filter(u => u.agent), cand = all.filter(u => agFits(u) && !ags.agents.some(a => a.agent_id === u.id));
    const sw = a => `<label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" data-fshlisten="${a.agent_id}" ${a.listen ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('Agent listens in')}${a.listen == null ? ` <small class="muted">${tr('not set')}</small>` : ''}</span></label>`;
    box.innerHTML = (ags.agents.length ? `<div class="members" id="fsh-agents">${ags.agents.map(a => `<div class="mrow fshag" data-aid="${a.agent_id}">${av(a.agent_id, a.name)}<span class="n">${esc(a.name)}${agentBadge()} ${a.first ? `<small class="muted">${tr('default for the lists')}</small>` : `<button type="button" class="linkbtn" data-fshfirst="${a.agent_id}">${tr('Make default')}</button>`}</span><button class="iconbtn" data-fshagrm="${a.agent_id}" title="${esc(tr('Stop sharing with {0}', a.name))}" aria-label="${esc(tr('Stop sharing with {0}', a.name))}">${ic('x', 's')}</button></div><div class="fshagsw">${sw(a)}</div>`).join('')}</div>`
      : ags.inherited.length ? `<div class="shint keep">${ic('folder', 's')} ${esc(tr('From the folder “{0}”:', fDisp(fParent(f))))} ${esc(ags.inherited.map(a => a.name).join(', '))}</div>` : `<div class="muted mhint">${tr('No agent')}</div>`)
      + (users === null ? '' : cand.length ? `<div class="mrow madd"><select id="fsh-agadd" aria-label="${esc(tr('Agent'))}"><option value="">${tr('Add an agent …')}</option>${cand.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select><button class="btn sm" data-m="fsh-agadd">${ic('plus', 's')} ${tr('Add')}</button></div>`
        : all.some(u => !agFits(u)) ? `<div class="muted mhint">${tr('The other agents work in another workspace.')}</div>` : '');
    st('ag', ags.agents.length ? ags.agents.map(a => a.name).join(', ') : tr('No agent'));
  };
  const loadAgents = async () => { try { ags = await api('GET', '/api/folders/agents?folder=' + encodeURIComponent(f)); } catch { ags = {agents: [], inherited: [], lists: []}; } drawAgents(); };
  const drawPub = j => {
    const box = $('#fsh-pub', md); if (!box) return;
    const ls = j.lists || [], on = ls.filter(x => x.link), can = ls.filter(x => !x.health);
    box.innerHTML = `<div class="shint lhint keep">${tr('People without an account can open the lists of this folder through a secret link each: read only, without comments, assignees or files.')}</div>`
      + (!j.enabled ? `<div class="muted mhint">${tr('Public links are turned off on this server')}</div>`
        : !ls.length ? `<div class="muted mhint">${tr('Applies to new lists in this folder. Shared lists of others keep their settings.')}</div>`
        : `${on.length ? `<div class="members fshpubl">${on.map(x => `<div class="mrow"><span class="n">${esc(x.name)}</span><button type="button" class="btn sm" data-fshcopy="${esc(x.link.url)}">${ic('copy', 's')} ${tr('Copy link')}</button></div>`).join('')}</div>` : ''}
          <div class="row"><button type="button" class="btn sm ${on.length ? '' : 'pri'}" data-m="fsh-pubon" ${can.length > on.length ? '' : 'hidden'}>${ic('link', 's')} ${on.length ? tr('Links for the other lists too') : tr('Create public links')}</button><button type="button" class="btn sm" data-m="fsh-puboff" ${on.length ? '' : 'hidden'}>${tr('Turn all off')}</button></div>
          ${ls.some(x => x.health) ? `<div class="shint keep">${ic('lock', 's')} ${esc(tr('Health lists stay private: they never get a public link.'))}</div>` : ''}`)
      + fshGrey(tr('Access') + ' · ' + tr('Valid until') + ' · ' + tr('Password'), tr('Per list in its Share dialog (the folder creates read-only links without a password).'));
    st('pub', on.length ? trn('{0} list', '{0} lists', on.length) : tr('Off'));
  };
  const loadPub = () => api('GET', '/api/folders/public-links?folder=' + encodeURIComponent(f)).then(drawPub).catch(() => { const b = $('#fsh-pub', md); if (b) b.innerHTML = ''; });
  const drawOwn = () => {
    const box = $('#fsh-own', md); if (!box) return;
    const mine = folderLists(f).filter(l => isOwner(l) && !l.is_inbox);
    box.innerHTML = `<div class="muted mhint">${esc(S.me?.display_name || '')}</div>`
      + (mine.length ? `<div class="row owrow"><button class="btn sm" data-m="fsh-xfer">${ic('user', 's')} ${tr('Transfer ownership of all lists…')}</button></div><div class="shint lhint">${esc(trn('Your {0} list in this folder goes to the person you choose; you stay in it as list admin.', 'Your {0} lists in this folder go to the person you choose; you stay in them as list admin.', mine.length))}</div>`
        : fshGrey(tr('Transfer ownership of all lists…'), tr('No list of yours in this folder')));
    st('own', S.me?.display_name || '');
  };
  const reload = async () => { try { have = (await api('GET', '/api/folders/people?folder=' + encodeURIComponent(f))).people; } catch { have = []; } drawPeople(); st('people', ''); };
  api('GET', '/api/users').then(j => { users = j.users.filter(u => !u.disabled && S.me && u.id !== S.me.id).map(u => ({id: u.id, display_name: u.display_name, agent: !!(u.agent || u.kind === 'agent'), org_id: u.org_id ?? null})); drawPeople(); drawAgents(); }).catch(() => { users = []; drawPeople(); drawAgents(); });
  reload(); drawGroups(); if (agentsOn()) loadAgents(); if (S.publicLinks) loadPub(); drawOwn();
  ntfLoad($('#fp-ntf', md), 'folder', f, j => { st('ntf', ntfName(j.effective?.tpl)); if (opt.focus === 'ntf' && !md._ntfs) { md._ntfs = 1; $('#fp-sec-ntf', md)?.scrollIntoView?.({block: 'start'}); } });
  if (opt.focus === 'agents' || opt.focus === 'grp') setTimeout(() => $(opt.focus === 'grp' ? '#fsh-sec-grp' : '#fsh-sec-ag', md)?.scrollIntoView?.({block: 'start'}), 0);
  const done = async () => { await load(); render(); };
  md.addEventListener('change', async e => {
    const t = e.target;
    const s = t.closest('[data-fprole]');
    if (s) {
      const uid = +s.dataset.fprole, nm = have.find(x => x.user_id === uid)?.name || users?.find(x => x.id === uid)?.display_name || '?';
      const ap = await fg_askRoles(`/api/folders/people/diff?folder=${encodeURIComponent(f)}&user_id=${uid}&role=${s.value}`, nm);  // 2.46.0 (#1606)
      if (ap === null) { drawPeople(); return; }
      try { const j = await api('PUT', '/api/folders/people', {folder: f, user_id: uid, role: s.value, ...(ap ? {} : {apply: false})}); have = have.map(x => x.user_id === uid ? {...x, role: s.value} : x); toast(j.updated ? trn('Role changed in {0} list', 'Role changed in {0} lists', j.updated) : tr('Saved')); } catch { drawPeople(); } return; }
    const gr = t.closest('[data-fgrole]');
    if (gr) {
      const ap = await fg_askRoles(`/api/folders/groups/${gr.dataset.fgrole}/diff?folder=${encodeURIComponent(f)}&role=${gr.value}`, (S.groups || []).find(x => x.id === +gr.dataset.fgrole)?.name || '?');  // 2.46.0 (#1606)
      if (ap === null) { drawGroups(); return; }
      try { await api('PUT', `/api/folders/groups/${gr.dataset.fgrole}`, {folder: f, role: gr.value, ...(ap ? {} : {apply: false})}); await done(); drawGroups(); } catch { /* api() said it */ } return;
    }
    if (t.dataset.fshlisten) {
      const aid = +t.dataset.fshlisten, on = t.checked;
      try { ags = await api('PUT', '/api/folders/agents', {folder: f, agent_id: aid, listen: on}); drawAgents(); await done(); toast(on ? tr('Agent listens in') : tr('Agent only via @'), async () => { try { ags = await api('PUT', '/api/folders/agents', {folder: f, agent_id: aid, listen: !on}); drawAgents(); await done(); } catch { /* said */ } }); } catch { drawAgents(); }
    }
  });
  const agRes = (j, msg) => { ags = j; drawAgents(); const sk = (j.skipped || []).map(x => `${x.name}: ${(x.reasons || []).join(', ')}`); toast(sk.length ? sk.join(' · ') : msg); };
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { md.remove(); await done(); return; }
    if (m === 'fsh-props') { if (opt.back) { md.remove(); return; } modalSub(md, () => folderPropsModal(f, {back: true})); return; }  // 2.46.0 (#1604): the settings come back here with "Back", no stack
    if (m === 'add') {
      const uid = +$('#fp-user', md).value, role = $('#fp-role', md).value; if (!uid) return;
      try { const j = await api('PUT', '/api/folders/people', {folder: f, user_id: uid, role}); await reload(); toast(trn('{0} list shared', '{0} lists shared', j.shared)); await done(); } catch { /* api() said it */ }
      return;
    }
    if (m === 'fsh-mail') {
      const em = $('#fsh-email', md).value.trim(); if (!em) { $('#fsh-email', md).focus(); return; }
      try { await api('PUT', '/api/folders/people', {folder: f, email: em, role: 'edit'}); } catch { return; }
      $('#fsh-email', md).value = ''; toast(tr('If there is an account with this address, the folder is now shared with it.')); await reload(); await done(); return;
    }
    if (b.dataset.rm) {
      const uid = +b.dataset.rm, nm = have.find(x => x.user_id === uid)?.name || users?.find(x => x.id === uid)?.display_name || '?';
      menu(b, [{label: tr('Also remove from the lists in the folder'), sub: tr('{0} no longer sees them', nm), icon: 'x', fn: () => rm(uid, true)},
        {label: tr('Only stop sharing new lists'), sub: tr('The lists shared so far stay'), icon: 'pause', fn: () => rm(uid, false)}]);
      return;
    }
    if (m === 'fg-add') { const g = +$('#fg-add', md).value; if (g) { try { await api('PUT', `/api/folders/groups/${g}`, {folder: f, role: $('#fg-role', md).value}); await done(); drawGroups(); } catch { /* said */ } } return; }
    if (b.dataset.fgrm) { try { await api('DELETE', `/api/folders/groups/${b.dataset.fgrm}?folder=${encodeURIComponent(f)}`); await done(); drawGroups(); } catch { /* said */ } return; }
    if (m === 'fsh-agadd') {
      const aid = +$('#fsh-agadd', md).value; if (!aid) return;
      if (!await agSafeFirst()) return;  // 2.30.0 (#920): the one-time agent safety note, as in a list
      const first = !ags.agents.length;
      try { const j = await api('PUT', '/api/folders/agents', {folder: f, agent_id: aid}); agRes(j, first ? trn('Shared with the agent in {0} list', 'Shared with the agent in {0} lists', j.changed || 0) : tr('Added: lists in this folder can choose it')); await done(); } catch { /* said */ }
      return;
    }
    if (b.dataset.fshfirst) { try { agRes(await api('PUT', '/api/folders/agents', {folder: f, agent_id: +b.dataset.fshfirst, first: true}), tr('Default for the lists')); await done(); } catch { /* said */ } return; }
    if (b.dataset.fshagrm) {
      const aid = +b.dataset.fshagrm, nm = ags.agents.find(a => a.agent_id === aid)?.name || '?';
      menu(b, [{label: tr('Also remove from the lists in the folder'), sub: tr('{0} no longer sees them', nm), icon: 'x', fn: () => agRm(aid, true)},
        {label: tr('Only stop sharing new lists'), sub: tr('The lists shared so far stay'), icon: 'pause', fn: () => agRm(aid, false)}]);
      return;
    }
    if (m === 'fsh-pubon' || m === 'fsh-puboff') {
      if (m === 'fsh-puboff' && !await askConfirm(tr('Turn the public links off?'), tr('They stop working at once.'), {ok: tr('Turn off'), danger: true})) return;
      try { const j = await calReq('PUT', '/api/folders/public-links', {folder: f, on: m === 'fsh-pubon'}); drawPub(j); toast(m === 'fsh-pubon' ? trn('{0} public link created', '{0} public links created', j.created) : tr('Public links turned off')); } catch (x) { toast(x.message); }
      return;
    }
    if (b.dataset.fshcopy) { try { await navigator.clipboard.writeText(b.dataset.fshcopy); toast(tr('Link copied')); } catch { toast(b.dataset.fshcopy); } return; }
    if (m === 'fsh-xfer') {
      const cand = (users || []).filter(u => !u.agent);
      if (!cand.length) { toast(tr('No other users yet. An admin can add them in the settings.')); return; }
      menu(b, cand.map(u => ({label: u.display_name, icon: 'user', fn: async () => {
        if (!await askConfirm(tr('Transfer all your lists in “{0}” to {1}?', fDisp(f), u.display_name), tr('You stay in them as list admin. Each list can be handed back only by its new owner.'), {ok: tr('Transfer')})) return;
        try { const j = await api('POST', '/api/folders/owner', {folder: f, user_id: u.id}); await done(); drawOwn(); toast(j.skipped?.length ? `${trn('{0} list transferred', '{0} lists transferred', j.moved)} · ${j.skipped.map(x => `${x.name}: ${x.reason}`).join(' · ')}` : trn('{0} list transferred', '{0} lists transferred', j.moved)); } catch { /* said */ }
      }})));
    }
  });
  const rm = async (uid, remove) => {
    try { const j = await api('DELETE', '/api/folders/people', {folder: f, user_id: uid, ...(remove ? {remove: true} : {})}); have = have.filter(x => x.user_id !== uid); drawPeople(); if (remove) toast(trn('Removed from {0} list', 'Removed from {0} lists', j.removed || 0)); await done(); } catch { /* api() said it */ }
  };
  const agRm = async (aid, remove) => {
    try { const j = await api('DELETE', '/api/folders/agents', {folder: f, agent_id: aid, ...(remove ? {remove: true} : {})}); ags = j; drawAgents(); toast(remove ? trn('Removed from {0} list', 'Removed from {0} lists', j.removed || 0) : tr('New lists no longer get it')); await done(); } catch { /* said */ }
  };
  if (!own) $('#fsh-members', md)?.insertAdjacentHTML('beforebegin', `<div class="shint keep">${ic('info', 's')} ${tr('Only your own lists can be shared')}</div>`);
  return md;
}
// ---- 2.46.0 (#1606): a changed folder role would replace roles set per list: ask first. -> true (everywhere), false (only
// new lists / keep the own roles), null (cancel). No such list: true at once, as before.
async function fg_askRoles(url, who) {
  let ls = [];
  try { ls = (await api('GET', url)).lists || []; } catch { return true; }
  if (!ls.length) return true;
  const rn = r => tr((ROLES.find(x => x[0] === r) || [r, r])[1]);
  const shown = ls.slice(0, 4).map(x => `${x.name}: ${rn(x.role)}`).join(', ') + (ls.length > 4 ? ', …' : '');
  return new Promise(res => {
    let done = false;
    const md = modal(`<h3 id="fg-rq-t">${esc(tr('Replace the roles set per list?'))}</h3><div class="cdlg-b" id="fg-rq-b">${esc(trn('In {0} list {1} has a role of its own ({2}).', 'In {0} lists {1} has a role of its own ({2}).', ls.length, who, shown))}</div>
      <div class="foot fgrqf"><button type="button" class="btn" data-fgrq="x">${esc(tr('Cancel'))}</button><span class="spacer"></span><button type="button" class="btn" data-fgrq="new">${esc(tr('Only new lists'))}</button><button type="button" class="btn pri" data-fgrq="all">${esc(tr('Set everywhere'))}</button></div>`);
    md.classList.add('fgrqdlg');
    md.setAttribute('role', 'alertdialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'fg-rq-t'); md.setAttribute('aria-describedby', 'fg-rq-b');
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); };
    md.addEventListener('click', e => { const b = e.target.closest('[data-fgrq]'); if (b) fin(b.dataset.fgrq === 'all' ? true : b.dataset.fgrq === 'new' ? false : null); });
    onRemove(md, () => fin(null));
    setTimeout(() => $('[data-fgrq="all"]', md)?.focus(), 30);
  });
}
// ---- 2.46.0 (#1605): a group's picture (S.groups[].avatar: a preset SVG, an own photo, '' = the group symbol). fg_gav = the
// round picture of a group wherever groups stand (share dialogs, group admin, a task assigned to a group).
const fg_gUrl = gid => (S.groups || []).find(x => x.id === +gid)?.avatar || '';
const fg_gav = (gid, cls = 'avatar gav') => { const u = fg_gUrl(gid); return `<span class="${cls}${u ? ' pic' : ''}">${u ? `<img src="${esc(u)}" alt="" loading="lazy" decoding="async" draggable="false">` : ic('users', 's')}</span>`; };
const fg_gico = gid => { const u = fg_gUrl(gid); return u ? `<img class="fggimg" src="${esc(u)}" alt="" loading="lazy" decoding="async" draggable="false">` : ic('users', 's'); };
// the picker of the group dialog: presets, an own photo, none; the choice is saved with the group (Save / Create)
function fg_pickHtml(cur) {
  const up = cur.startsWith('/api/group-avatar/');
  return AV_PRESETS.map(([k, n]) => `<button type="button" class="avopt ${cur === `/static/avatars/${k}.svg` ? 'on' : ''}" data-fgav="${k}" title="${esc(tr(n))}" aria-label="${esc(tr(n))}" aria-pressed="${cur === `/static/avatars/${k}.svg`}"><img src="/static/avatars/${k}.svg" alt=""></button>`).join('')
    + `<button type="button" class="avopt up ${up ? 'on' : ''}" data-fgav="upload" title="${esc(tr('Upload a photo…'))}" aria-label="${esc(tr('Upload a photo…'))}" aria-pressed="${up}">${up ? `<img src="${esc(cur)}" alt="">` : ic('plus')}</button>`
    + `<button type="button" class="avopt none ${cur ? '' : 'on'}" data-fgav="none" title="${esc(tr('No picture (group symbol)'))}" aria-label="${esc(tr('No picture (group symbol)'))}" aria-pressed="${!cur}">${ic('users', 's')}</button>`;
}
const fg_pickRow = g => `<div class="row avrow"><label>${tr('Picture')}</label><div class="avpick" id="gr-avpick">${fg_pickHtml(g?.avatar || '')}</div></div>`;
function fg_pickWire(md, g) {  // -> () => the pending choice: null (unchanged) | {preset} | {none: true} | {blob, url}
  let pend = null;
  const box = $('#gr-avpick', md); if (!box) return () => null;
  const show = cur => { box.innerHTML = fg_pickHtml(cur); };
  box.addEventListener('click', e => {
    const b = e.target.closest('[data-fgav]'); if (!b) return;
    const k = b.dataset.fgav;
    if (k === 'none') { pend = {none: true}; show(''); return; }
    if (k !== 'upload') { pend = {preset: k}; show(`/static/avatars/${k}.svg`); return; }
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
    inp.addEventListener('change', async () => {
      const f = inp.files?.[0]; if (!f) return;
      if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
      const bl = await avCropModal(f); if (!bl || !md.isConnected) return;
      if (pend?.url) URL.revokeObjectURL(pend.url);
      pend = {blob: bl, url: URL.createObjectURL(bl)};
      box.innerHTML = fg_pickHtml('/api/group-avatar/new');
      const im = $('[data-fgav="upload"] img', box); if (im) im.src = pend.url;
    });
    inp.click();
  });
  onRemove(md, () => { if (pend?.url) URL.revokeObjectURL(pend.url); });
  return () => pend;
}
async function fg_pickSave(gid, pend) {  // after Save / Create; a failed picture keeps the group (api() says why)
  if (!pend || !gid) return;
  try {
    if (pend.none) await api('DELETE', `/api/admin/groups/${gid}/avatar`);
    else if (pend.preset) await api('PUT', `/api/admin/groups/${gid}/avatar`, {preset: pend.preset});
    else if (pend.blob) { const fd = new FormData(); fd.append('file', pend.blob, 'avatar.jpg'); await api('POST', `/api/admin/groups/${gid}/avatar`, fd); }
  } catch { /* api() said it */ }
}
// the old entry points stay (notification question, older links): they open the one dialog
function folderPeopleModal(f, opt = {}) { return folderShareModal(f, opt); }
// ---- 2.41.0 (#1428): a folder shows whether it is shared, with the symbols of a list (licShareHtml: people grey, the robot
// blue): my folder shared itself (people, groups, agents; a subfolder also by its top folder) -- "New lists here are shared
// with …"; a folder someone shared with me; a weaker sign when only lists inside are shared. Shown folded too.
function folderShareOf(f) {  // -> {people, groups, agents: [names]} or null
  if (!f) return null;
  const all = S.folderShares || {}, own = all[f], top = fParent(f) ? all[fParent(f)] : null;
  const people = (own?.people || 0) + (top?.people || 0), groups = (own?.groups || 0) + (top?.groups || 0);
  const agents = (own?.agents || []).length ? own.agents : top?.agents || [];
  return people || groups || agents.length ? {people, groups, agents} : null;
}
function folderShareTxt(sh) {  // "3 people, 1 group", "agent Claude" -> [persons part, agents part]
  const pp = [sh.people ? trn('{0} person', '{0} people', sh.people) : '', sh.groups ? trn('{0} group', '{0} groups', sh.groups) : ''].filter(Boolean).join(', ');
  const ap = sh.agents.length ? trn('agent {1}', 'agents {1}', sh.agents.length, sh.agents.join(', ')) : '';
  return [pp, ap];
}
function folderShareSay(sh, one, two) { const [pp, ap] = folderShareTxt(sh); return pp && ap ? tr(two, pp, ap) : tr(one, pp || ap); }
function folderShrHtml(f) {
  const sh = folderShareOf(f), si = !sh && folderSharedIn(f);
  if (sh || si) {
    const tip = sh ? folderShareSay(sh, N_('New lists here are shared with {0}'), N_('New lists here are shared with {0} and {1}')) : tr('Shared by {0}', si.owner_name);
    return `<span class="shr shk fshr" role="img" aria-label="${esc(tip)}" title="${esc(tip)}">${!sh || sh.people || sh.groups ? ic('users', 's') : ''}${sh?.agents.length ? licBot() : ''}</span>`;
  }
  const ls = (S.lists || []).filter(l => !l.archived && !l.is_inbox && fUnder(l.folder, f) && l.shared);
  if (!ls.length || !collab()) return '';
  const tip = trn('{0} list in here is shared; new lists stay private', '{0} lists in here are shared; new lists stay private', ls.length);
  return `<span class="shr shk fshr fshweak" role="img" aria-label="${esc(tip)}" title="${esc(tip)}">${ic('users', 's')}${ls.some(l => (l.shared_agents || []).length) ? licBot() : ''}</span>`;
}
// moved / dragged one of my lists into a shared folder: say so (the caller offers Undo)
function folderNowShared(id, f) {
  const l = listById(id), sh = f && folderShareOf(f);
  return l && sh && isOwner(l) ? folderShareSay(sh, N_('Now shared with {0}'), N_('Now shared with {0} and {1}')) : '';
}
