// @ts-check
/* Kalmido web client: the Share dialog of a project (shareModal: people, groups, agents, notifications, public link) (2.1156.0, #4280: moved here from dialogs.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// 2.32.0 (#1058): the parts below "People" fold (closed at first, a short state in the folded line); people stay open.
// Ids of the old headings stay (l-pub-h, sh-own-h, sh-ag-h, sh-grp-h) for links and tests.
const SH_HID = {grp: 'sh-grp-h', ag: 'sh-ag-h', pub: 'l-pub-h', own: 'sh-own-h', ntf: 'sh-ntf-h'};  // 2.33.0 (#927): + notifications
const SH_ADP = {sec: k => 'sh-sec-' + k, st: k => 'sh-st-' + k, hid: SH_HID};
const shSec = (k, title, inner, hide = false, open = false) => shSecHtml(SH_ADP, k, title, inner, hide, open);
// 2.550.0 (#4528): what removing a member ended (lists/membermemo.py): the numbers as text, the memos of a project, the question
const mmText = d => [d?.assigned && trn('{0} assignment', '{0} assignments', d.assigned), d?.values && trn('{0} person field value', '{0} person field values', d.values),
  d?.delegate && trn('{0} delegated task', '{0} delegated tasks', d.delegate), d?.watch && trn('{0} watched task', '{0} watched tasks', d.watch)].filter(Boolean).join(', ');
async function mmLoad(lid) {
  try { const j = await rawFetch('GET', `/api/lists/${lid}/member-memos`); return Object.fromEntries((j.memos || []).filter(m => m.member).map(m => [m.user_id, m])); } catch { return {}; }
}
async function mmAsk(lid, uid, name, offer, after) {
  if (!await askConfirm(tr('Restore what {0} had in this project?', name), tr('When they were removed, this ended: {0}. Only what nobody has taken over since comes back.', mmText(offer)), {ok: tr('Restore')})) return;
  let j; try { j = await api('POST', `/api/lists/${lid}/members/${uid}/restore`); } catch { return; }
  const n = Object.values(j.restored || {}).reduce((a, x) => a + x, 0);
  toast(tr('Restored: {0}.', mmText(j.restored) || '0') + (j.skipped ? ' ' + trn('{0} item stayed as it is (taken over or gone since).', '{0} items stayed as they are (taken over or gone since).', j.skipped) : ''));
  if (n) await after?.();
}
function shareModal(id, opt = {}) {
  const l0 = listById(id); if (!shareOk(l0)) return;
  const own = isOwner(l0);
  /** @type {any} */
  const md = modal(shFrameHtml({title: tr(collab() ? N_('Share “{0}”') : N_('Owner of “{0}”'), lname(l0)), setAct: 'list-edit', setIcon: 'edit', setLabel: tr('Project settings…'), body: `
    ${collab() ? `<div class="shws" id="sh-ws"></div>` : ''}
    ${collab() ? `<h4 id="sh-people-h">${tr('People')}</h4><div class="members shppl" id="l-members" aria-labelledby="sh-people-h">${/*html-ok*/ loadingHtml()}</div>` : ''}${dsc_on() ? `<button type="button" class="linkbtn dsc-sharelink" data-dsc-open>${tr('Find a person …')}</button>` : ''}${''/* 2.49.0 (#1106) */}
    ${collab() && typeof ln_shareHint === 'function' ? ln_shareHint(id) : ''}${''/* 2.48.0 (#1642): locked notes stay unreadable */}
    ${collab() && (S.peopleVis === 'contacts' || S.instanceMode === 'workspaces') && canManage(l0) ? `<div class="row shmail"><input id="sh-email" type="email" autocomplete="off" placeholder="${esc(tr('Share by e-mail address'))}" aria-label="${esc(tr('Share by e-mail address'))}"><button type="button" class="btn sm" data-m="share-mail">${ic('send', 's')} ${tr('Share')}</button></div><div class="members shopen" id="sh-open"></div>` : ''}
    ${collab() ? shSec('grp', tr('Groups'), `<div id="sh-grpwrap"></div>`, true) : ''}
    ${collab() && agentsOn() ? shSec('ag', tr('Agents'), `<div class="shint lhint keep">${tr('An agent sees exactly the projects shared with it, nothing else. Stopping the sharing ends its access at once.')}</div><div id="sh-agwrap"></div>`, !canManage(l0) && !listPeople(l0).some(p => p.agent || agentById(p.user_id))) : ''}${''/* 2.910.0 (#5442): shown from the start where it will be (no step when the people have loaded) */}
    ${own && collab() ? shSec('ntf', tr('Notifications for members'), `<div id="sh-ntf"><div class="muted mhint">${tr('Loading…')}</div></div>`, false, opt.focus === 'ntf') : ''}
    ${!own && collab() ? ntfMemberHint(l0) : ''}
    ${own && pubOn('lists') && l0.e2e && typeof le2u_pubHtml === 'function' ? shSec('pub', tr('Public link'), le2u_pubHtml()) : ''}${''/* 2.64.1 (#1817) */}
    ${own && pubOn('lists') && !l0.e2e ? shSec('pub', tr('Public link'), `<div id="l-pub"><div class="muted mhint">${tr('Loading…')}</div></div>`) : ''}
    ${shSec('own', tr('Owner'), `<div id="sh-ownwrap"><div class="muted mhint" id="sh-owner"></div><div id="l-owner"></div></div>`, false, !collab())}
`}));  // 2.910.0 (#5442): the shared frame (shFrameHtml)
  md.classList.add('shmodal');
  let users = null, memos = null;  // 2.550.0 (#4528): memos = user id -> what their removal ended (owner and project admins)
  const shSecSet = (k, show, st) => { const sec = $('#sh-sec-' + k, md); if (!sec) return; sec.hidden = !show; const e = $('#sh-st-' + k, md); if (e) e.textContent = st || ''; };
  const roleSel = shRoleSel;  // 2.910.0 (#5442): the shared role choice
  const isAg = p => !!(p.agent || agentById(p.user_id));
  const row = (cur, p, mng) => `<div class="mrow" data-uid="${p.user_id}">${avBtn(p.user_id, p.name)}<span class="n">${esc(p.name)}${S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : ''}${isAg(p) ? agentBadge(p.user_id) : ''}${p.via_group ? ` <span class="muted">${tr('via a group')}</span>` : ''}${p.via_folder && cur.folder ? ` <span class="muted lfvia">${esc(tr('via the folder {0}', fDisp(cur.folder)))}</span>` : ''/* 2.352.0 E (#2748) */}</span>${mng && p.role !== 'owner' && !(S.me && p.user_id === S.me.id) && !p.via_group
      ? `${memos?.[p.user_id] ? `<button type="button" class="iconbtn" data-mmrest="${p.user_id}" title="${esc(tr('Restore what {0} had in this project', p.name))}" aria-label="${esc(tr('Restore what {0} had in this project', p.name))}">${ic('undo', 's')}</button>` : ''/* 2.550.0 (#4528) */}${roleSel(`data-mrole="${p.user_id}"`, p.role, tr('Role of {0}', p.name))}<button class="iconbtn" data-mrm="${p.user_id}" title="${esc(isAg(p) ? tr('Stop sharing with {0}', p.name) : tr('Remove from project'))}" aria-label="${esc(isAg(p) ? tr('Stop sharing with {0}', p.name) : tr('Remove {0} from this project', p.name))}">${ic('x', 's')}</button>`
      : `<span class="muted" title="${esc(roleHelp(p.role))}">${esc(roleLabel(p.role))}</span>`}</div>`;
  const draw = () => {
    if (!md.isConnected) return;
    const cur = listById(id) || l0, people = listPeople(cur), mng = canManage(cur);
    const box = $('#l-members', md);
    if (box) {
      const ppl = people.filter(p => !isAg(p));
      // 2.28.0 (#935): an organisation's list is shared only with its members; 2.46.4 (#1737): the others are greyed out with the reason
      const cand = users && users.filter(u => !u.agent && u.id !== S.me?.id && !people.some(p => p.user_id === u.id));
      shWsFill($('#sh-ws', md), cur.org_id || null, own && !cur.is_inbox ? () => $('[data-m="list-edit"]', md)?.click() : null);
      box.innerHTML = ppl.map(p => row(cur, p, mng)).join('') +
        (mng ? (users === null ? `${/*html-ok*/ loadingHtml()}` : cand.length ? `<div class="mrow madd"><select id="l-adduser" aria-label="${esc(tr('Invite'))}"><option value="">${tr('Share with …')}</option>${shWsOptions(cand, cur.org_id || null)}</select>${roleSel('id="l-addrole"', 'edit')}<button class="btn sm" data-m="share">${ic('plus', 's')} ${tr('Add')}</button></div>`
          : `<div class="muted mhint">${users.filter(u => !u.agent).length > 1 ? tr('Shared with everyone') : noPeopleTxt()}</div>`) + `<details class="rolehelp sdet"><summary>${tr('What the roles may do')}</summary>${ROLES.map(([, n, h]) => `<div><b>${tr(n)}</b> <span class="muted">${tr(h)}</span></div>`).join('')}</details>`
          : `<div class="muted mhint olock"><span>${esc(tr('Owner'))}: ${esc(cur.owner_name)}</span><button type="button" class="iconbtn" data-m="owner-info" title="${esc(tr('Owner: {0}. The owner and project admins rename and archive this project and manage who is in it; the rest of its settings stays with the owner.', cur.owner_name))}" aria-label="${esc(tr('Owner: {0}. The owner and project admins rename and archive this project and manage who is in it; the rest of its settings stays with the owner.', cur.owner_name))}">${ic('lock', 's')}</button></div>`);
    }
    const aw = $('#sh-agwrap', md);
    if (aw) {
      const agFits = u => !wsOn() || (u.org_id || null) === (cur.org_id || null);  // 2.28.0 (#935): agents of the list's workspace
      const ags = people.filter(isAg), acand = users ? users.filter(u => u.agent && !people.some(p => p.user_id === u.id) && agFits(u)) : [];
      aw.innerHTML = ags.length || (mng && acand.length) ? `<div class="members" id="sh-agents">${mng && !agentById(cur.owner_id) && (users || []).some(u => u.agent && agFits(u)) ? '' : ags.map(p => row(cur, p, mng)).join('')}${mng && !agentById(cur.owner_id) && (users || []).some(u => u.agent && agFits(u)) ? `<div class="row"><label for="sh-agsel">${tr('Agent')}</label><select id="sh-agsel"><option value="">${tr('No agent')}</option>${users.filter(u => u.agent && (agFits(u) || ags.some(p => p.user_id === u.id))).map(u => `<option value="${u.id}" ${ags[0]?.user_id === u.id ? 'selected' : ''}>${esc(u.display_name)}${!agFits(u) ? ' · ' + esc(tr('other workspace')) : ''}</option>`).join('')}</select></div>` : ''}${ags.some(p => !agFits((users || []).find(u => u.id === p.user_id) || {org_id: cur.org_id})) ? `<div class="shint keep">${ic('alert', 's')} ${esc(tr('This agent works in another workspace (from before the workspaces). Take it out of the project, or keep it on purpose.'))}</div>` : ''}</div>
        <div id="l-tidyrow">${tidyRowHtml(cur)}</div>` : '';
      if (!aw.innerHTML && !$('#sh-sec-ag', md)?.hidden) aw.innerHTML = `<div class="muted mhint">${esc(users === null && mng ? tr('Loading…') : tr('No agent'))}</div>`;  // 2.910.0 (#5442)
      shSecSet('ag', !!aw.innerHTML, ags.length ? ags.map(p => p.name).join(', ') + (listenOn(cur) ? ' · ' + tr('listens in') : '') : tr('No agent'));
    }
    const gw = $('#sh-grpwrap', md);  // 2.10.0 (#441)
    if (gw) { const gh = shareGroupsHtml(cur, mng, roleSel); gw.innerHTML = gh ? `<div class="members" id="sh-groups" aria-labelledby="sh-grp-h">${gh}</div>` : ''; shSecSet('grp', !!gh, trn('{0} group', '{0} groups', (cur.groups || []).length)); }
    const ow = $('#sh-owner', md); if (ow) ow.textContent = cur.owner_name || (own ? S.me?.display_name || '' : '');
    shSecSet('own', true, cur.owner_name || (own ? S.me?.display_name || '' : ''));
    const sum = $('#l-shsum'); if (sum) sum.textContent = shareSummary(cur);
    if (typeof le2u_share === 'function') le2u_share(md, id);  // 2.64.1 (#1817): key state per person, no participants / agents
  };
  // "Transfer ownership…" (owner) / "Take over…" (admins, owner = agent or disabled user) + the history (2.1.2, #349)
  const drawOwner = async () => {
    const box = $('#l-owner', md); if (!box) return;
    let j; try { j = await calReq('GET', `/api/lists/${id}/owner`); } catch { box.innerHTML = ''; return; }
    if (!md.isConnected) return;
    box._j = j;
    const hist = j.history.slice(0, 3).map(h => `<div class="muted mhint owhist">${esc(tr('Ownership transferred from {0} to {1}', h.from, h.to))} · ${esc(relTime(h.at))}</div>`).join('');
    const why = j.owner.agent ? tr('The owner is the agent {0}: agents cannot manage who is in a project. As an admin you can take it over.', j.owner.name)
      : tr('The owner {0} is disabled. As an admin you can take the project over.', j.owner.name);
    box.innerHTML = (j.mode === 'owner' ? `<div class="row owrow"><button class="btn sm" data-m="own-xfer">${ic('user', 's')} ${tr('Transfer ownership…')}</button></div>`
      : j.mode === 'takeover' ? `<div class="shint keep lhint">${esc(why)}</div><div class="row owrow"><button class="btn sm" data-m="own-xfer">${ic('user', 's')} ${tr('Take over…')}</button></div>` : '') + hist;
  };
  draw(); drawOwner();
  adsFill($('#sh-open', md), 'kind=list&ref=' + id);  // 2.1071.0 (#5658)
  if (own && pubOn('lists') && !l0.e2e) pubWire(md, id);
  if (own && collab() && $('#sh-ntf', md)) ntfLoad($('#sh-ntf', md), 'list', id, j => { shSecSet('ntf', true, ntfName(j.effective?.tpl)); if (opt.focus === 'ntf' && !md._ntfs) { md._ntfs = 1; $('#sh-sec-ntf', md)?.scrollIntoView?.({block: 'start'}); } });  // 2.33.0 (#927)
  if (collab()) {
    tidyWire(md, id);
    md.addEventListener('change', async (/** @type {any} */ e) => {  // 2.26.0: the list's one agent (switching = old out, new in, with Undo)
      if (e.target.id !== 'sh-agsel') return;
      await setListAgent(id, e.target.value ? +e.target.value : null, (users || []).filter(u => u.agent).map(u => ({id: u.id, name: u.display_name})), draw);
      draw();
    });
    // 2.27.0 (#974): opened from "Agent…": scrolled to the Agents part, its choice focused
    const toAgents = () => { if (opt.focus !== 'agents' || !md.isConnected) return; const sec = $('#sh-sec-ag', md); if (sec) sec.open = true; const el = $('#sh-agsel', md) || $('#sh-ag-h', md); el?.scrollIntoView?.({block: 'center'}); $('#sh-agsel', md)?.focus({preventScroll: true}); };
    if (canManage(l0)) mmLoad(id).then(m => { memos = m; draw(); });  // 2.550.0 (#4528)
    if (canManage(l0)) api('GET', '/api/users').then(j => { users = j.users.filter(u => !u.disabled).map(u => ({id: u.id, display_name: u.display_name, agent: !!u.agent, orgs: u.orgs || [], org_id: u.org_id ?? null})); /* 2.28.0 (#935): + the workspace */ draw(); toAgents(); }).catch(() => { users = []; draw(); });
  }
  const act = async (fn, msg) => { try { await fn(); await load(); render(); if (canManage(listById(id) || l0)) memos = await mmLoad(id); draw(); if (msg) toast(msg); } catch { /* api() showed it */ } };
  md.addEventListener('change', (/** @type {any} */ e) => {
    const r = e.target.closest('[data-mrole]');
    if (r) act(() => api('PUT', `/api/lists/${id}/members`, {user_id: +r.dataset.mrole, role: r.value}));
    const gr = e.target.closest('[data-grole]');
    if (gr) act(() => api('PUT', `/api/lists/${id}/groups/${gr.dataset.grole}`, {role: gr.value}));
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { md.remove(); return; }
    if (m === 'list-edit') { if (opt.back) { md.remove(); return; } modalSub(md, () => listModal(id, '', {back: true})); return; }  // 2.46.0 (#1604): back to here, no stack
    if (m === 'share-mail') {  // 2.22.0 (#752): mode "own contacts": share by address; the answer never says whether it has an account
      const em = $('#sh-email', md).value.trim(); if (!em) { $('#sh-email', md).focus(); return; }
      try { await api('PUT', `/api/lists/${id}/members`, {email: em, role: 'edit'}); } catch { return; }
      $('#sh-email', md).value = ''; toast(tr('If there is an account with this address, the project is now shared with it.')); adsFill($('#sh-open', md), 'kind=list&ref=' + id); await load(); render(); return;
    }
    if (m === 'share' || m === 'share-ag') {
      const [us, rs] = m === 'share' ? ['#l-adduser', '#l-addrole'] : ['#sh-addagent', '#sh-agrole'];
      const u = +$(us, md).value; if (!u) return;
      if (m === 'share-ag' && !await agSafeFirst()) return;  // 2.30.0 (#920)
      let offer = null;
      await act(async () => { offer = (await bridgeTry(ok => api('PUT', `/api/lists/${id}/members`, {user_id: u, role: $(rs, md).value, ...(ok ? {bridge_ok: true} : {})})))?.restore_offer; }, tr('Shared'));  // 2.30.0 (#919)
      if (offer) await mmAsk(id, u, (users || []).find(x => x.id === u)?.display_name || '', offer, () => act(() => null));  // 2.550.0 (#4528)
      return;
    }
    if (b.dataset.mrm) {
      const p = listPeople(listById(id)).find(x => x.user_id === +b.dataset.mrm), ag = p && isAg(p);
      let dTxt = ''; try { const d = await rawFetch('DELETE', `/api/lists/${id}/members/${b.dataset.mrm}?dry=1`); const t = mmText(d); if (t) dTxt = ' ' + tr('Of theirs in this project, this ends: {0}.', t) + (d.days ? ' ' + trn('Adding them again within {0} day offers to restore it.', 'Adding them again within {0} days offers to restore it.', d.days) : ''); } catch { /* the question without the number */ }  // 2.272.0 E2 (#3038); 2.550.0 (#4528): + delegations, watching, the way back
      if (!await askConfirm(ag ? tr('Stop sharing with {0}?', p?.name || '') : tr('Remove {0} from this project?', p?.name || ''), (ag ? tr('The agent loses access to this project and its tasks at once.') : tr('They no longer see the project and its tasks; their tasks stay.')) + dTxt, {ok: ag ? tr('Stop sharing') : tr('Remove'), danger: true})) return;
      act(() => api('DELETE', `/api/lists/${id}/members/${b.dataset.mrm}`)); return;
    }
    if (b.dataset.mmrest) { const uid = +b.dataset.mmrest, mm = memos?.[uid]; if (mm) await mmAsk(id, uid, mm.name, mm, () => act(() => null)); return; }  // 2.550.0 (#4528)
    if (m === 'share-grp') { const g = +$('#l-addgrp', md).value; if (g) act(() => api('PUT', `/api/lists/${id}/groups/${g}`, {role: $('#l-grprole', md).value}), tr('Shared')); return; }
    if (b.dataset.grm) {
      const g = (listById(id)?.groups || []).find(x => x.group_id === +b.dataset.grm);
      if (!await askConfirm(tr('Stop sharing with the group {0}?', g?.name || ''), tr('Its members lose access unless they have it personally or through another group.'), {ok: tr('Stop sharing'), danger: true})) return;
      act(() => api('DELETE', `/api/lists/${id}/groups/${b.dataset.grm}`)); return;
    }
    if (m === 'owner-info') { toast(b.title); return; }
    if (m === 'own-xfer') { const j = $('#l-owner', md)?._j; if (j) ownerModal(id, lname(listById(id) || l0), j, () => md.remove()); return; }
  });
  return md;
}
