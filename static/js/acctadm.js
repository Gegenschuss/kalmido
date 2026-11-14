// @ts-check
/* Kalmido web client: the settings sections of account.js that only the settings dialog draws (Workspaces pane, sign-up / sign-in / OIDC, storage, backups) (2.1156.0, #4280: moved here from account.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

async function actDraw(md) {
  const box = $('#s-act', md); if (!box) return;
  let j; try { j = await api('GET', '/api/admin/orgs/activity'); } catch { box.innerHTML = ''; return; }
  const row = (n, o) => `<tr><th scope="row">${esc(n)}</th><td>${o.members}</td><td>${o.last_login ? esc(o.last_login) : '–'}</td><td>${esc(fmtBytes(o.storage_bytes))}</td><td>${o.lists}</td><td>${o.tasks}</td></tr>`;
  box.className = 'actwrap'; box.tabIndex = 0; box.setAttribute('role', 'region'); box.setAttribute('aria-labelledby', 's-act-h');  // 2.364.0 C (#3041): now in view under People: the wide table scrolls by keyboard too
  box.innerHTML = `<table class="acttbl"><thead><tr><th>${tr('Organisation')}</th><th>${tr('Members')}</th><th>${tr('Last sign-in')}</th><th>${tr('Storage')}</th><th>${tr('Projects')}</th><th>${tr('Tasks')}</th></tr></thead><tbody>${
    j.orgs.map(o => row(o.name, o)).join('')}${row(tr('Without organisation'), j.private)}</tbody></table>`;
}
async function wsPaneDraw(md) {
  const box = $('#s-ws', md); if (!box) return;
  let j; try { j = await api('GET', '/api/orgs'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  const mm = Object.keys(j.mismatches || {}).length;
  // 2.364.0 C (#3041): with Organisation > Data in the dialog the data boxes of each organisation go there (one place)
  const dbox = $('#s-wsdata', md), inl = !dbox, dataBoxes = o => ocBoxHtml(o) + oxBoxHtml(o) + (typeof rxBoxHtml === 'function' ? rxBoxHtml('org', o.id) : '');
  const org = o => `<details class="sdet wsorg" data-oid="${o.id}" ${j.orgs.length === 1 ? 'open' : ''}><summary>${o.icon_url ? orgIconHtml(o) : `<span class="fem" aria-hidden="true">${o.icon ? esc(o.icon) : ic('building')}</span>`}<b>${esc(o.name)}</b> <span class="muted">${esc(trn('{0} member', '{0} members', o.members.filter(m => !m.agent).length))} · ${esc(trn('{0} project', '{0} projects', o.lists))}${o.role === 'admin' ? ' · ' + esc(tr('you are an admin')) : o.role && o.role !== 'member' ? ' · ' + esc(tr('your role: {0}', oinvRoleSel.label(o.role))) : ''}</span></summary>
    ${/*html-ok*/ o.members.map(m => `<div class="mrow ${m.disabled ? 'off' : ''}">${av(m.id, m.name)}<span class="n">${esc(m.name)}${m.agent ? ' ' + agentBadge(m.id) : ''}${m.id === S.me?.id ? ' ' + tr('(me)') : ''}${m.pending ? ` <span class="muted">· ${tr('waits for approval')}</span>` : ''}</span>${o.role === 'admin' && m.pending ? `<button class="btn sm pri" data-wsok="${m.id}">${ic('check', 's')} ${tr('Approve')}</button>${''/* 2.464.0 (#3882) */}` : ''}${o.role === 'admin' && j.manage && !m.agent ? `${oinvRoleSel('', m.role, o.roles || [], `data-wsrole="${m.id}" aria-label="${esc(tr('Role of {0}', m.name))}"`)}${''/* 2.143.0 A (#2151) */}<button class="iconbtn${m.id !== S.me?.id ? ' ms-phsr' : ''}" data-wsrm="${m.id}" title="${esc(m.id === S.me?.id ? tr('Leave the organisation') : tr('Remove from the organisation'))}" aria-label="${esc(m.id === S.me?.id ? tr('Leave the organisation') : tr('Remove {0} from the organisation', m.name))}">${ic('x', 's')}</button>${m.id !== S.me?.id ? `<button class="iconbtn danger ms-phsr" data-wsdel="${m.id}" title="${esc(tr('Delete account'))}" aria-label="${esc(tr('Delete the account of {0}', m.name))}">${ic('trash', 's')}</button>${/*html-ok*/ ms_dots('.ms-phsr', m.name) /* 2.1151.0 C (#3835): one "…" on a phone */}` : ''/* 2.88.0 (#1980) */}` : `<span class="muted">${m.agent ? tr('Agent') : esc(oinvRoleSel.label(m.role))}</span>`}</div>`).join('')}
    ${o.role === 'admin' && j.manage ? oinvRoleSel.help(o.roles || []) : ''}
    ${o.role === 'admin' && j.manage ? `<div class="row wsadd"><button type="button" class="btn sm" data-oinv="new">${ic('send', 's')} ${tr('Invite people')}</button></div>${''/* 2.364.0 C (#3041): one dialog (e-mail or link) instead of the field + Add */}
    <div class="row"><label for="ws-name-${o.id}">${tr('Name')}</label><input id="ws-name-${o.id}" value="${esc(o.name)}" maxlength="60" data-wsf="name"><label for="ws-dom-${o.id}">${tr('E-mail domains')}</label><input id="ws-dom-${o.id}" value="${esc(o.domains || '')}" ${S.me?.is_admin ? 'placeholder="example.com" data-wsf="domains"' : 'readonly'}></div>${S.me?.is_admin ? '' : `<div class="muted mhint" id="ws-dom-hint-${o.id}">${tr('Only an admin of this server sets the e-mail domains of an organisation')}</div>`}` : ''}${''/* 2.166.0 (#2633): name and domains save themselves (no Save button); 2.467.0 (#3898): domains read only unless an admin of the server */}
    ${o.role === 'admin' && j.manage ? `<div class="row wsic"><label>${tr('Symbol')}</label><span class="wsicprev">${orgIconHtml(o)}</span><input type="file" id="ws-icfile-${o.id}" accept="image/jpeg,image/png,image/webp,image/gif" hidden data-wsicf><button type="button" class="btn sm" data-wsic="up">${ic('picture', 's')} ${tr('Upload a picture…')}</button>${o.icon_url ? `<button type="button" class="btn sm" data-wsic="rm">${tr('Remove the picture')}</button>` : ''}</div>` : ''}${''/* 2.87.9 (#1913) */}
    ${o.role === 'admin' ? `<div class="row"><button type="button" class="btn sm" data-oadm="${o.id}">${ic('list', 's')} ${tr('Projects of the organisation')}</button><button type="button" class="btn sm" data-otk="${o.id}">${ic('done', 's')} ${tr('Tasks of the organisation')}</button></div>` : ''}${''/* 2.574.0 (#3376): + the read-only task view */}
    ${o.role === 'admin' && inl ? dataBoxes(o) : ''}${''/* 2.42.0 (#828): encryption + recovery key, export; 2.146.0 D (#2468): the retention export */}
    ${o.role === 'admin' ? whoBoxHtml(o) : ''}${''/* 2.115.0 A (#2061): the organisation's webhooks; lazy-ok: 2.149.0 F (#2519): settings dialog only (LD_NEED loads integrations) */}
    ${o.role === 'admin' && typeof chn_orgBoxHtml === 'function' ? chn_orgBoxHtml(o) : ''}${''/* 2.142.0 A (#2145): its notification channels */}
    ${o.role !== 'admin' || !j.manage ? `<div class="row"><button class="btn sm" data-wsrm="${S.me?.id}" data-oidx="${o.id}">${ic('logout', 's')} ${tr('Leave the organisation')}</button></div>` : ''}</details>`;
  box.innerHTML = (j.orgs.length ? j.orgs.map(org).join('') : `<div class="muted mhint">${tr('You belong to no organisation: everything is private.')}</div>`)
    + (mm ? `<div class="shint keep">${ic('alert', 's')} ${esc(trn('{0} project of yours has an agent of another workspace (from before the workspaces). Open the project’s Share dialog to take it out or keep it.', '{0} projects of yours have an agent of another workspace (from before the workspaces). Open the projects’ Share dialogs to take it out or keep it.', mm))}</div>` : '');
  // 2.186.0 A (#2599): retired organisations I was an admin of: no members any more, only their export until they go for good
  if (dbox) { dbox._j = j; dbox.innerHTML = j.orgs.filter(o => o.role === 'admin').map(o => `<div class="wsdorg" data-oid="${o.id}"><h5 class="wsdname">${esc(o.name)}</h5>${dataBoxes(o)}</div>`).join(''); }
  if ((j.retired || []).length) (dbox || box).insertAdjacentHTML('beforeend', j.retired.map(o => `<details class="sdet wsret"><summary><b>${esc(o.name)}</b> <span class="muted">${odlRetiredLabel(o)}</span></summary>
    <div class="shint">${esc(tr('You were an admin of this organisation before it was retired: you can still export it until it is deleted permanently.'))}</div>
    ${oxBoxHtml(o)}${typeof rxBoxHtml === 'function' ? rxBoxHtml('org', o.id) : ''}</details>`).join(''));
  if (!S.me?.kid) (dbox || box).insertAdjacentHTML('beforeend', `<div class="ocorg">${ocBoxHtml({id: 0}, {title: `${tr('Your private office')}: ${tr('Encryption')}`})}</div>`);  // 2.138.0 C (#1972): its recovery key (hidden without encrypted data)
  oxDraw(box);  // 2.42.0 (#833): the export sections of the organisations I administer
  if (dbox) { oxDraw(dbox); ocDraw(dbox); }  // 2.364.0 C (#3041)
  whoDraw(box);  // 2.115.0 A (#2061): their webhooks; lazy-ok: settings dialog only (LD_NEED settings -> integrations)
  if (typeof chn_orgDraw === 'function') chn_orgDraw(box);  // 2.142.0 A (#2145): their notification channels
  ocDraw(box);  // 2.42.0 (#828): their encryption sections
  wsc_paneDraw(box);  // 2.53.0 (#1474): each organisation's colour (its admins choose)
  pmeta_paneDraw(box);  // 2.61.0 B (#1819): whether photos lose their metadata on upload (its admins choose)
  if (typeof chn_contentPaneDraw === 'function') chn_contentPaneDraw(box);  // 2.240.0 B (#2867): content to personal forwardings
  if (typeof xl_paneDraw === 'function') xl_paneDraw(box);  // 2.112.1 B (#2058): external share links of its files allowed
  if (typeof oag_paneDraw === 'function') oag_paneDraw(box);  // 2.361.4 (#2928): members may keep their own agents in it
  wsa_orgPaneDraw(box);  // 2.409.0 (#3490): the areas its members see (its admins decide)
  if (typeof asst_orgPaneDraw === 'function') asst_orgPaneDraw(box);  // 2.240.0 A (#2884): the assistant and other members' comments
  if (typeof oinvDraw === 'function') oinvDraw(box);  // 2.115.0 B (#2062): invite by e-mail + the open invitations
}
function wsPaneWire(md) {
  md.addEventListener('change', async (/** @type {any} */ e) => {
    const t = e.target;  // 2.633.0 (#4920): the symbol's fixed file input (wsPaneDraw)
    if (t.dataset?.wsicf !== undefined && t.files?.length) { const fl = t.files[0]; t.value = ''; wsIconFile(md, +t.closest('[data-oid]').dataset.oid, fl); return; }
    const f = e.target.dataset?.wsf;
    if (f) {  // 2.166.0 (#2633): the organisation's name / e-mail domains save when the field is left (the settings pattern of #2247)
      const el = e.target, oid = +el.closest('[data-oid]').dataset.oid, v = f === 'name' ? el.value.trim() : el.value;
      if (f === 'name' && !v) { el.value = el.defaultValue; return; }
      try { await api('PATCH', `/api/orgs/${oid}`, {[f]: v}); } catch { el.value = el.defaultValue; return; }
      el.defaultValue = el.value;
      if (typeof setSaved === 'function' && $('.ssaved', md)) setSaved(null); else toast(tr('Saved'));
      if (f === 'name') { await load(); render(); wsPaneDraw(md); }
      return;
    }
    const r = e.target.dataset?.wsrole; if (!r) return;
    const oid = +e.target.closest('[data-oid]').dataset.oid;
    try { await api('PUT', `/api/orgs/${oid}/members`, {user_id: +r, role: e.target.value}); toast(tr('Saved')); } catch { /* shown */ }
    wsPaneDraw(md);
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const oa = e.target.closest('[data-oadm]');
    if (oa) { const o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === +oa.dataset.oadm); oadmOpen(+oa.dataset.oadm, o?.name || ''); return; }  // 2.35.0 (#1101)
    const otk = e.target.closest('[data-otk]');
    if (otk) { const o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === +otk.dataset.otk); otkOpen(+otk.dataset.otk, o?.name || ''); return; }  // 2.574.0 (#3376)
    const wi = e.target.closest('[data-wsic]');
    if (wi) {  // 2.87.9 (#1913)
      const oid = +wi.closest('[data-oid]').dataset.oid;
      if (wi.dataset.wsic === 'up') { $(`#ws-icfile-${oid}`, md)?.click(); return; }  // 2.633.0 (#4920): fixed hidden file input, its change uploads (a drop onto the window too, dropany.js)
      wsIconPick(md, oid, wi.dataset.wsic); return;
    }
    const ok = e.target.closest('[data-wsok]');
    if (ok) { try { await api('POST', `/api/users/${ok.dataset.wsok}/approve`, {}); toast(tr('Approved: the person can sign in now')); } catch { /* shown */ } wsPaneDraw(md); return; }  // 2.464.0 (#3882)
    const wd = e.target.closest('[data-wsdel]');
    if (wd) {  // 2.88.0 (#1980): an organisation admin deletes an account of only this organisation (else: remove, lists to a member)
      const o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === +wd.closest('[data-oid]').dataset.oid), m = o?.members.find(x => x.id === +wd.dataset.wsdel);
      const r = m && await ua8_delete({id: m.id, display_name: m.name});  // lazy-ok: 2.149.0 F (#2519): the settings dialog (acctset.js) drew this pane
      if (r) { if (r === true) toast(tr('Deleted')); await load(); render(); wsPaneDraw(md); }
      return;
    }
    const b = e.target.closest('[data-wsadd],[data-wsrm]'); if (!b) return;
    const oid = +(b.dataset.oidx || b.closest('[data-oid]')?.dataset.oid || 0);
    try {
      if (b.dataset.wsadd) { const em = $('#ws-add-' + oid, md).value.trim(); if (!em) return; const r = await api('PUT', `/api/orgs/${oid}/members`, {email: em}); toast(S.me?.is_admin ? (r.by_email ? tr('If this address has an account, the person is now a member.') : tr('Added')) : tr('Invitation sent. With an account, the person accepts it in their News.')); }  // 2.148.1 A (#2480)
      else if (b.dataset.wsrm) {
        const uid = +b.dataset.wsrm, self = uid === S.me?.id, o = (($('#s-ws', md)._j || {}).orgs || []).find(x => x.id === oid), m = o?.members.find(x => x.id === uid);
        const li = await api('GET', `/api/orgs/${oid}/leave-info${self ? '' : '?uid=' + uid}`).catch(() => null);  // 2.361.0 (#2922): what goes where
        const nq = self ? outOrgEntries(oid).length : 0;  // 2.538.0 (#4369): unsent changes of this organisation wait in this device's queue
        if (!await askConfirm(self ? tr('Leave the organisation “{0}”?', o?.name || '') : tr('Remove {0} from the organisation?', m?.name || ''), li ? '' : (self ? tr('Your projects of this workspace go to one of its admins and you leave every project of the organisation.') : tr('The person’s projects of this workspace come to you and the person leaves every project of the organisation.')) + ' ' + tr('Tasks of the organisation assigned to them are unassigned and they no longer come along to any; joining again within 24 hours brings that back for the tasks they can see then.'), {ok: self ? tr('Leave') : tr('Remove'), danger: true, ...(li || nq ? {html: (li ? olvLeaveHtml(li, self) : '') + outOrgWarnHtml(nq)} : {})})) return;  // 2.273.0 B (#3042): + what ends
        await api('DELETE', `/api/orgs/${oid}/members/${uid}`); if (self) outOrgDrop(oid); toast(self ? tr('You left the organisation') : tr('Removed'));  // 2.538.0 (#4369): its queue entries go with it
      }
      await load(); render();
    } catch { /* api() showed it */ }
    wsPaneDraw(md);
  });
}
// 2.538.0 (#4369): the line in the leave dialog when unsent changes of the organisation wait on this device
const outOrgWarnHtml = n => n ? `<div class="shint keep olvrow warn">${ic('alert', 's')} ${esc(trn('{0} change of this organisation has not been sent yet; it is discarded when you leave.', '{0} changes of this organisation have not been sent yet; they are discarded when you leave.', n))}</div>` : '';
// 2.361.0 (#2922): the leave / remove dialog lists every area: back to the private space, to an admin, stays, ends
function olvLeaveHtml(j, self) {
  const rows = [], th = j.to_heir || {};
  if ((j.back || []).length) rows.push([false, (self ? tr('Back to your private workspace (you brought them in): {0}', j.back.join(', ')) : tr('Back to the person’s private workspace (brought in by them): {0}', j.back.join(', ')))]);
  if (j.back_text) rows.push([false, (self ? tr('Back to your private workspace too: {0}', j.back_text) : tr('Back to the person’s private workspace too: {0}', j.back_text))]);  // 2.365.1 (#3395)
  if (j.kept) rows.push([true, (self ? trn('{0} item you brought in cannot go back by itself and stays. Ask an admin to release it before you leave.', '{0} items you brought in cannot go back by themselves and stay. Ask an admin to release them before you leave.', j.kept) : trn('{0} item the person brought in cannot go back by itself and stays.', '{0} items the person brought in cannot go back by themselves and stay.', j.kept))]);
  const given = [th.lists ? trn('{0} project', '{0} projects', th.lists) : '', th.calendars ? trn('{0} calendar', '{0} calendars', th.calendars) : '', th.books ? trn('{0} address book', '{0} address books', th.books) : ''].filter(Boolean).join(', ');
  if (given) rows.push([false, tr('Goes to {0}: {1}', j.heir || tr('an admin'), given)]);
  if (j.stays_text) rows.push([true, (self ? tr('Stays in the organisation, you no longer see it: {0}', j.stays_text) : tr('Stays in the organisation, the person no longer sees it: {0}', j.stays_text))]);
  if (j.assigned) rows.push([false, trn('{0} task of the organisation assigned to them is unassigned.', '{0} tasks of the organisation assigned to them are unassigned.', j.assigned)]);
  rows.push([false, (self ? tr('You leave every project of the organisation; joining again does not bring that back.') : tr('The person leaves every project of the organisation; joining again does not bring that back.'))]);
  return rows.map(([w, t]) => `<div class="shint keep olvrow${w ? ' warn' : ''}">${w ? ic('alert', 's') + ' ' : ''}${esc(t)}</div>`).join('');
}
// 2.87.9 (#1913): an organisation admin sets an own picture as its symbol (cropped square like a list icon) or removes it;
// 2.161.0 (#2594): after = what to redraw instead of the workspaces pane (the admin dialog "Edit organisation")
const wsIconDone = async (md, after) => { toast(tr('Saved')); await load(); render(); after ? await after() : wsPaneDraw(md); };
async function wsIconPick(md, oid, how, after) {
  if (how === 'rm') { try { await api('DELETE', `/api/orgs/${oid}/icon`); await wsIconDone(md, after); } catch { /* api() showed it */ } return; }
  const f0 = fpass_take(); if (f0) { wsIconFile(md, oid, f0, after); return; }  // 2.633.0 (#4920): a fixed input before the button (data-fpass)
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/gif';
  inp.addEventListener('change', () => { const f = inp.files?.[0]; if (f) wsIconFile(md, oid, f, after); });
  inp.click();
}
// 2.633.0 (#4920): the chosen / dropped picture of an organisation's symbol: checked, cropped, uploaded
async function wsIconFile(md, oid, f, after) {
  if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
  const bl = await avCropModal(f, {title: tr('Symbol'), png: true, square: true}); if (!bl) return;
  const fd = new FormData(); fd.append('file', bl, 'icon.png');
  try { await api('POST', `/api/orgs/${oid}/icon`, fd); await wsIconDone(md, after); } catch { /* api() showed it */ }
}
// ---- 2.23.0 (#711): registration on the login page (admins): the mode and the e-mail domains
const SIGNUP_UI = [['off', N_('Off: only admins add people')], ['domain', N_('Only addresses of certain e-mail domains')], ['approval', N_('Anyone, after an admin approves')], ['open', N_('Anyone with a confirmed e-mail address')]];
function signupAdminHtml(a) {
  const mode = a.signup_mode || 'off', org = !!a.has_orgs;  // 2.46.0 (#1592): any server with an organisation
  const priv = !!a.signup_private;  // 2.422.0 (#2937): private accounts register without an invitation (a server with an organisation)
  const dis = k => (k === 'domain' || k === 'open') && !a.mail_out ? 'disabled' : k === 'open' && org && !priv ? 'disabled' : '';
  return `<h4 id="s-signup-h">${tr('Registration on the sign-in page')}</h4>
    <div class="row"><label for="s-signup">${tr('Who can register')}</label><select id="s-signup">${SIGNUP_UI.map(([k, n]) => `<option value="${k}" ${k === mode ? 'selected' : ''} ${dis(k)}>${esc(tr(n))}</option>`).join('')}</select></div>
    <div class="row" id="s-sdomrow" ${mode === 'domain' ? '' : 'hidden'}><label for="s-sdom">${tr('E-mail domains')}</label><input id="s-sdom" value="${esc(a.signup_domains || '')}" placeholder="example.com, example.org" autocapitalize="off"></div>
    <div class="shint">${esc([tr('New people confirm their address with a link (or wait for an admin), choose their password and start without access to projects: share projects with them. Never an admin or a child account.'),
      a.mail_out ? '' : tr('Without e-mail sending (SMTP) only “after an admin approves” works.'), org && !priv ? tr('This server has organisations: open registration is not possible (only their e-mail domains or with approval).') : ''].filter(Boolean).join(' '))}</div>
    ${org ? `<label class="wide"><input type="checkbox" id="s-spriv" ${priv ? 'checked' : ''}><span>${tr('Private accounts register without an invitation')}<small class="muted">${tr('Then “Anyone with a confirmed e-mail address” works here too: such an account stays private and never joins an organisation by its address; a company’s admin invites the person. Off by default.')}</small></span></label>` : ''}
    <label class="wide"><input type="checkbox" id="s-oinv" ${a.org_invites !== false ? 'checked' : ''}><span>${tr('Organisation admins may invite new people by e-mail')}<small class="muted">${tr('They get an account in that organisation and an e-mail to choose a password. Off: only admins of the server create accounts.')}</small></span></label>
    <label class="wide"><input type="checkbox" id="s-cinv" ${a.cinv_signup ? 'checked' : ''}><span>${tr('People without an account register with an invitation link')}<small class="muted">${tr('Anyone may invite someone by a link or QR code (Find people); the new account is private and connected with the inviting person. On by default when anyone may register.')}</small></span></label>`;  // 2.115.0 B (#2062); 2.1156.0 (#4550): s-cinv
}
// ---- Settings > Users > Whole server: sign-in (2FA policy, passkey login, OIDC) (2.555.0 C, #4664: heading "Two-factor and passkeys", the sub-tab is called Sign-in)
function signinHtml(hint) {
  /** @type {any} */
  const a = S.about || {}, o = a.oidc || {};
  let h = `<h4 id="s-signin-h">${tr('Two-factor and passkeys')}</h4>
    <div class="featgrid">
      <label class="wide"><input type="checkbox" id="s-2fareq" ${a.twofa_required ? 'checked' : ''}><span>${tr('Require two-factor authentication for built-in sign-ins')}<small class="muted">${tr('Everyone who signs in with a password must set up an authenticator app or a passkey at the next sign-in. Single sign-on sign-ins (sign-in proxy, OIDC) are not affected: there the sign-in provider is responsible.')}</small></span></label>
      <label class="wide"><input type="checkbox" id="s-pklogin" ${a.passkey_login !== false ? 'checked' : ''}><span>${tr('Allow signing in with a passkey without the password')}<small class="muted">${tr('A passkey someone added in Settings > Account then also works on its own (the device asks for the fingerprint, face or PIN).')}</small></span></label>
    </div>
    ${signupAdminHtml(a)}
    <h4 id="s-oidc-h">${tr('Sign-in with an OIDC provider')}</h4>`;
  if (!o.configured) return h + hint(tr('Not configured yet. Sign in with Authentik, Keycloak, Authelia, PocketID, Google, Microsoft Entra or any other OpenID Connect provider: fill in the provider below (or set the KALMIDO_OIDC_* variables) and register this redirect URI at the provider: {0}', `<code class="topic">${esc(o.redirect_uri || '')}</code>`)) + oidcForm(o, hint);
  const row = (l, v) => v ? `<div class="row"><label>${l}</label><code class="topic">${esc(v)}</code></div>` : '';
  h += row(tr('Provider'), o.issuer) + row(tr('Client ID'), o.client_id) +
    `<div class="row"><label>${tr('Redirect URI')}</label><code class="topic" id="s-oidcredir">${esc(o.redirect_uri)}</code><button class="btn sm" data-m="oidc-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>` +
    row(tr('Scopes'), o.scopes) + row(tr('User name claim'), o.username_claim) + row(tr('Required group'), o.required_group) + row(tr('Admin group'), o.admin_group) +
    row(tr('Admin e-mail domains'), o.admin_domains) +
    hint(tr('The client secret is {0}.', o.secret_set ? tr('set') : tr('not set (public client with PKCE)')) + ' ' +
      trn('{0} person is linked to the provider.', '{0} people are linked to the provider.', o.linked || 0)) +
    `<div class="featgrid"><label class="wide"><input type="checkbox" id="s-oidcauto" ${o.autocreate ? 'checked' : ''}><span>${tr('Create accounts on the first OIDC sign-in')}<small class="muted">${tr('Off: only users an admin created can sign in; the first sign-in links them by their verified e-mail. On: anyone the provider lets through gets an account, and accounts made for single sign-on are also linked by user name.')}</small></span></label></div>`;
  if (o.error) h += `<div class="shint cnote">${tr('Last problem with the provider: {0}', esc(o.error))}</div>`;
  return h + oidcForm(o, hint);
}
// 2.9.0 (#438): the provider set up here (stored, the client secret encrypted with KALMIDO_SECRET_KEY); a field set by a
// KALMIDO_OIDC_* variable is locked (the environment wins)
const OIDC_DOCS = 'https://github.com/Gegenschuss/kalmido/blob/main/docs/OIDC.md';
const OIDC_FORM = [['issuer', N_('Provider'), 'https://auth.example.com/application/o/kalmido/'], ['client_id', N_('Client ID'), ''], ['client_secret', N_('Client secret'), ''],
  ['scopes', N_('Scopes'), 'openid profile email'], ['username_claim', N_('User name claim'), 'preferred_username'], ['groups_claim', N_('Groups claim'), 'groups'],
  ['required_group', N_('Required group'), ''], ['admin_group', N_('Admin group'), ''], ['admin_domains', N_('Admin e-mail domains'), 'example.com'], ['label', N_('Button label'), 'OpenID Connect']];
function oidcForm(o, hint) {
  const env = new Set(o.env || []), st = o.stored || {}, dr = o.draft?.fields || {};
  const f = OIDC_FORM.map(([k, n, ph]) => {
    const lock = env.has(k), sec = k === 'client_secret';
    const val = lock ? (sec ? '' : o[k === 'admin_domains' ? 'admin_domains' : k] || '') : sec ? '' : k in dr ? dr[k] : st[k] || '';  // 2.166.0 (#2633): the draft's value first
    const pl = lock ? tr('set by the server environment') : sec ? (o.draft?.secret === 'new' ? tr('entered, not in effect yet') : o.draft?.secret === 'removed' ? tr('removed, not in effect yet') : o.secret_set && !env.has(k) ? tr('set (unchanged)') : tr('empty = public client with PKCE')) : ph;
    return `<div class="row"><label for="oi-${k}">${tr(n)}</label><input id="oi-${k}" data-oik="${k}" ${sec ? 'type="password" autocomplete="new-password"' : 'autocomplete="off" spellcheck="false"'} value="${esc(val)}" placeholder="${esc(pl)}" ${lock ? 'readonly' : ''}>${sec && (o.secret_set || o.draft?.secret === 'new') && o.draft?.secret !== 'removed' && !lock ? `<button class="btn sm" data-oidc="secret-del">${tr('Remove')}</button>` : ''}</div>`;
  }).join('');
  return `<details class="shelp sdet oidcform" ${o.configured && !o.draft ? '' : 'open'}><summary>${o.configured ? tr('Change the provider settings') : tr('Set up the provider')}</summary>
    ${hint(tr('Each field is saved as a draft: the sign-in keeps its current settings until the draft passed “Check connection” and you switch it on.'))}
    ${f}
    ${hint(tr('Admin e-mail domains: comma-separated. Whoever signs in with a verified e-mail of one of them becomes an admin, like the admin group (and no longer is one otherwise; the last admin always stays).'))}
    ${env.size ? hint(tr('Fields set with KALMIDO_OIDC_* environment variables are locked here: the environment always wins.')) : ''}
    ${o.secret_lost ? `<div class="shint cnote">${tr('The stored client secret cannot be read with the current KALMIDO_SECRET_KEY: enter it again.')}</div>` : ''}
    ${!o.secret_key && !env.has('client_secret') ? `<div class="shint iiok">${tr('Without KALMIDO_SECRET_KEY on the server the client secret can only be set as an environment variable.')}</div>` : ''}
    <div id="oi-draft">${oidcDraftHtml(o)}</div>
    <div class="shint" id="oi-res" role="status" aria-live="polite"></div></details>`;
}
// 2.166.0 (#2633): the draft's state, "Check connection" and the switch that puts a checked draft into effect
function oidcDraftHtml(o) {
  const d = o.draft;
  const sw = d ? `<div class="featgrid"><label class="wide"><input type="checkbox" id="oi-on" ${d.checked ? '' : 'disabled'}><span>${o.configured ? tr('Use the changed settings for the sign-in') : tr('Sign-in with this provider')}<small class="muted">${d.checked ? tr('The connection was checked. On = in effect at once.') : d.complete ? tr('Not in effect yet: check the connection first.') : tr('Not in effect yet: fill in the provider and the client ID.')}</small></span></label></div>` : '';
  return `${sw}<div class="row">${d?.complete || o.configured ? `<button class="btn sm" data-oidc="check">${ic('check', 's')} ${tr('Check connection')}</button>` : ''}${d ? `<button class="btn sm" data-oidc="discard">${tr('Discard draft')}</button>` : ''}<a class="btn sm" href="${OIDC_DOCS}" target="_blank" rel="noopener noreferrer">${ic('help', 's')} ${tr('Provider guides')}</a></div>`;
}
function oidcWire(md) {
  const res = () => $('#oi-res', md);
  const took = (o, full) => {
    if (S.about) S.about.oidc = o;
    if (full) { const box = $('#s-signin', md); if (box) box.innerHTML = signinHtml(t => `<div class="shint">${t}</div>`); return; }
    const dr = $('#oi-draft', md); if (dr) dr.innerHTML = oidcDraftHtml(o);
    const sec = $('#oi-client_secret', md);  // the secret's field shows what the draft does with it
    if (sec) { sec.value = ''; sec.placeholder = o.draft?.secret === 'new' ? tr('entered, not in effect yet') : o.draft?.secret === 'removed' ? tr('removed, not in effect yet') : o.secret_set ? tr('set (unchanged)') : tr('empty = public client with PKCE'); }
  };
  const saved = () => { if (typeof setSaved === 'function' && $('.ssaved', md)) setSaved(null); else toast(tr('Saved')); };
  // 2.166.0 (#2633): a field saves into the draft when it is left (the sign-in in effect stays as it is)
  md.addEventListener('change', async (/** @type {any} */ e) => {
    const i = e.target;
    if (i.id === 'oi-on') {
      if (!i.checked) return;
      i.disabled = true;
      // 2.306.0 D1 (#2875): a change of who becomes an admin asks for the account password
      const apply = async b => { try { return await rawFetch('POST', '/api/admin/oidc/draft/apply', b); } catch (x) { if (x.data?.password_needed || x.data?.reauth_needed) throw x; throw new Error(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); } };
      try {
        let j; try { j = await apply({}); } catch (x) {
          if (x.data?.reauth_needed) { if (!await reauthFresh(x.data)) throw new Error(tr('Cancelled|dialog')); j = await apply({}); } else {  // 2.611.0 (#4019)
          if (!x.data?.password_needed) throw x;
          const p = await pwPrompt(tr('Confirm with your password')); if (!p) throw new Error(tr('Cancelled|dialog'));
          j = await apply({password: p.password}); }
        }
        took(j, true); toast(tr('The sign-in uses the new settings'));
      }
      catch (x) { i.checked = false; i.disabled = false; const r = res(); if (r) r.textContent = x.message; }
      return;
    }
    const k = i.dataset?.oik; if (!k || i.readOnly) return;
    if (k === 'client_secret' && !i.value) return;
    const r = res(); if (r) r.textContent = '';
    try { took(await calReq('PUT', '/api/admin/oidc/draft', {[k]: k === 'client_secret' ? i.value : i.value.trim()})); saved(); }
    catch (x) { if (r) r.textContent = x.message; }
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-oidc]'); if (!b) return;
    const r = res(), a = b.dataset.oidc;
    b.disabled = true;
    try {
      if (a === 'check') {
        const dr = !!S.about?.oidc?.draft;
        const j = await calReq('POST', '/api/admin/oidc/check', dr ? {draft: true} : {});
        if (j.draft && S.about?.oidc) took({...S.about.oidc, draft: j.draft});
        else if (dr && S.about?.oidc?.draft) took({...S.about.oidc, draft: {...S.about.oidc.draft, checked: false}});
        const rr = res(); if (rr) rr.textContent = j.ok ? tr('The provider answers: {0}', j.issuer) : tr('Provider check failed: {0}', j.error);
        return;
      }
      if (a === 'discard') { took(await calReq('DELETE', '/api/admin/oidc/draft'), true); toast(tr('Discarded')); return; }
      if (a === 'secret-del') { took(await calReq('PUT', '/api/admin/oidc/draft', {client_secret: ''})); b.remove(); saved(); }
    } catch (x) { if (r) r.textContent = x.message; } finally { b.disabled = false; }
  });
}
// ---- Settings > Users > Whole server > Backups
// 2.13.0: "Check storage": files of tasks / projects that are missing, empty or cut off on disk (read-only)
const stoHtml = () => `<h4 id="s-sto-h">${tr('Check storage')}</h4><div class="row"><button class="btn sm" data-m="sto-check">${ic('search', 's')} ${tr('Check storage')}</button></div><div id="s-sto" role="status" aria-live="polite"></div><div id="s-scn"></div><div id="s-ret"></div>`;  // 2.61.0 (#1818): + s-scn; 2.223.3 A (#2877): + s-ret
// 2.61.0 (#1818): the virus scanner's state below "Check storage" (one line; drawn once per opening)
async function scnStatus(md) {
  const box = $('#s-scn', md); if (!box || box.dataset.done) return;
  box.dataset.done = '1';
  retStatus(md);  // 2.223.3 A (#2877)
  let j; try { j = await api('GET', '/api/admin/upload-scan'); } catch { box.dataset.done = ''; return; }
  const st = j.state === 'off' ? tr('Virus scanner: off (KALMIDO_CLAMD is not set). Uploads are not checked.')
    : j.state === 'ok' ? tr('Virus scanner: active.') : tr('Virus scanner: not reachable. Uploads are taken and marked “Unchecked”; the check follows once it runs again.');
  const n = [j.unchecked ? trn('{0} file waits for the check', '{0} files wait for the check', j.unchecked) : '', j.infected ? trn('{0} locked file (malware found)', '{0} locked files (malware found)', j.infected) : ''].filter(Boolean);
  box.innerHTML = `<div class="shint${j.state === 'down' || j.infected ? ' cnote' : ''}">${esc(st)}${n.length ? ' ' + esc(n.join(' · ')) : ''}</div>`;
}
// 2.223.3 A (#2877): the deletion runs of the server (GET /api/admin/retention): per kind whether they delete or only count,
// what their last pass deleted or would have deleted (numbers only) and the switch in .env
const RET_KIND = {trash: N_('Trash'), logs: N_('Logs'), backups: N_('Safety backups'), files: N_('Orphan files'), chat: N_('Agent chat')};
async function retStatus(md) {
  const box = $('#s-ret', md); if (!box || box.dataset.done) return;
  box.dataset.done = '1';
  let j; try { j = await api('GET', '/api/admin/retention'); } catch { box.dataset.done = ''; return; }
  const due = v => Object.values(v.runs || {}).reduce((n, r) => n + Object.entries(r.counts || {}).reduce((m, [x, c]) => m + (/_locked$|_err$|kept/.test(x) ? 0 : c), 0), 0);
  const ks = Object.entries(j.kinds || {}), off = ks.some(([, v]) => !v.on);
  const li = ([k, v]) => `<li><b>${esc(tr(RET_KIND[k] || k))}</b> <span class="muted">${esc(v.on ? tr('deletes') : tr('counts only'))} · ${esc(!v.last ? tr('not run yet')
    : v.on ? trn('{0} item deleted in the last pass', '{0} items deleted in the last pass', due(v)) : trn('{0} item would have been deleted in the last pass', '{0} items would have been deleted in the last pass', due(v)))}</span></li>`;
  box.innerHTML = `<h4 id="s-ret-h">${tr('Deletion runs')}</h4>${off ? `<div class="shint">${esc(tr('Runs that only count delete nothing, not even after the trash period. Switch them on with {0} in the .env file and restart the server.', `${j.general_switch || 'KALMIDO_RETENTION_PURGE'}=1`))}</div>` : ''}<ul class="stol">${ks.map(li).join('')}</ul>${j.env_buffer ? `<div class="shint" id="s-ret-buf">${esc(tr('Records kept by law (receipts, books, logbook, business letters) are kept {0} years longer than the law asks. Change it with {1} in the .env file (0 = exactly the law, never shorter).', j.buffer_years, j.env_buffer))}</div>` : ''}`;  // 2.545.0 (#4595)
}
async function stoCheck(md) {
  const box = $('#s-sto', md); if (!box) return;
  box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`;
  let j; try { j = await api('GET', '/api/admin/storage-check'); } catch { box.innerHTML = ''; return; }
  const P = {missing: N_('missing'), empty: N_('empty'), size: N_('incomplete')};
  box.innerHTML = !j.problems.length ? `<div class="muted mhint">${esc(trn('{0} file checked, all fine', '{0} files checked, all fine', j.checked))}</div>`
    : `<div class="mhint warn">${esc(trn('{0} damaged or missing file', '{0} damaged or missing files', j.problems.length))}</div><ul class="stol">${j.problems.map(p => `<li><b>${esc(p.name)}</b> <span class="muted">${esc(p.where)} · ${esc(tr(P[p.problem]))}</span>${p.kind === 'attachment' && p.owner ? ` <button class="linkbtn" data-act="open-id" data-id="${p.owner}">${tr('Open')}</button>` : ''}</li>`).join('')}</ul>`;
}
const bkHtml = () => `<h4 id="s-bk-h">${tr('Backups')}</h4><div class="shint">${tr('The server key KALMIDO_SECRET_KEY is not part of a backup: keep it separately. A backup restores the encrypted organisation data only with that key (or with the organisations’ recovery keys).')}</div><div id="s-bk"><div class="muted mhint">${tr('Loading…')}</div></div><h4 id="s-bko-h">${tr('Off-site backup')}</h4><div id="s-bko"></div>`;  // 2.143.0 B (#2152): + the off-site target
const BK_KIND = {auto: N_('automatic'), manual: N_('manual'), safety: N_('before a restore')};
async function bkDraw(md, j) {
  const box = $('#s-bk', md); if (!box) return;
  scnStatus(md);  // 2.61.0 (#1818): the virus scanner's line (once)
  if (!j) { try { j = await api('GET', '/api/admin/backups'); } catch (x) { box.innerHTML = `<div class="muted mhint">${x.status === 404 ? esc(x.message) : tr('Only available online.')}</div>`; return; } }
  box._j = j;
  const hint = t => `<div class="shint">${t}</div>`;
  let h = `<div class="featgrid"><label class="wide"><input type="checkbox" id="bk-on" ${j.on ? 'checked' : ''}><span>${tr('Automatic backups')}<small class="muted">${tr('Every day a copy of the database and all attachments goes into the folder {0} on the server. Copy that folder somewhere else too (another disk, your usual server backup): a backup on the same disk does not help if the disk dies.', `<code>${esc(j.dir)}</code>`)}</small></span></label></div>
    <div class="row"><label for="bk-time">${tr('Time')}</label>${timeIn('bk-time', j.time, {label: tr('Time'), clear: false})}</div>
    <div class="row"><label for="bk-daily">${tr('Keep')}</label><input type="number" class="aanum" id="bk-daily" min="1" max="365" value="${j.keep_daily}"><span class="muted">${tr('daily')}</span><input type="number" class="aanum" id="bk-weekly" min="0" max="${j.keep_weekly_max || 104}" value="${j.keep_weekly}"><span class="muted">${tr('weekly')}</span></div>
    ${j.keep_weekly_max ? hint(tr('Weekly backups are kept for at most {0} weeks (data protection).', j.keep_weekly_max)) : ''}
    <div class="featgrid"><label class="wide"><input type="checkbox" id="bk-enc" ${j.encrypt || j.encrypt_required ? 'checked' : ''} ${j.encrypt_required ? 'disabled' : ''}><span>${tr('Encrypt backups')}<small class="muted">${tr('AES-256 with a passphrase. Without the passphrase an encrypted backup cannot be restored, not even by you or the admin. Write it down somewhere safe (password manager).')}</small></span></label></div>
    ${j.encrypt_required ? hint(tr('This server only writes encrypted backups: set a passphrase (at least 10 characters).')) : j.encrypt ? '' : `<div class="shint cnote bkencnote">${tr('Backups are not encrypted: whoever can read the backup folder can read all data in it.')}</div>`}
    <div class="row"><label for="bk-pass">${tr('Passphrase')}</label><input type="password" id="bk-pass" autocomplete="new-password" placeholder="${j.passphrase_env ? tr('set by the server operator') : j.passphrase_set ? tr('set (unchanged)') : tr('at least 10 characters')}" ${j.passphrase_env ? 'readonly' : ''}><button type="button" class="btn sm" data-bk="pcheck" ${j.passphrase_set ? '' : `disabled title="${esc(tr('No backup passphrase is set yet.'))}"`}>${tr('Check passphrase')}</button></div>
    ${j.passphrase_set ? '' : hint(tr('Check passphrase: no backup passphrase is set yet.'))}
    <div class="row"><button class="btn sm" data-bk="now" ${j.running ? 'disabled' : ''}>${ic('archive', 's')} ${tr('Back up now')}</button></div>`;
  const st = [j.running ? (j.running === 'restore' ? tr('A restore is running…') : tr('Backup running…')) : j.last_ok ? tr('Last backup: {0}.', esc(aaWhen(j.last_ok))) : tr('No backup yet.'),
    tr('Backups use {0}, {1} free on the disk.', fmtBytes(j.total_bytes), j.free_bytes ? fmtBytes(j.free_bytes) : '?')];
  h += hint(st.join(' '));
  // 2.432.0 (#3584): larger files are kept once for all backups (the sizes below are without them)
  if (j.store_files) h += `<div class="shint bkstore">${trh('Shared files of all backups: {0} in {1} (each file is kept only once).', fmtBytes(j.store_bytes), trn('{0} file', '{0} files', j.store_files))}</div>`;
  // 2.209.0 E (#1627): little room left for further backups (less than three of the newest one's size)
  const each = j.items.length ? j.items[0].size + (j.items[0].store_new_bytes || 0) : 0;  // 2.432.0 (#3584): + its new shared files
  if (j.free_bytes && j.items.length && j.free_bytes < 3 * each) h += `<div class="shint cnote bkspace">${trh('Little space left on the disk for further backups (each one about {0}). Keep fewer backups or give the backup folder a bigger disk.', fmtBytes(each))}</div>`;
  if (j.last_error) h += `<div class="shint cnote">${tr('The last backup failed ({0}): {1}', esc(aaWhen(j.last_error_at)), esc(j.last_error))}</div>`;
  if ((j.leftovers || []).length) h += `<div class="shint cnote" id="bk-leftovers">${tr('Folders from a restore are lying next to the data folder ({0}). After a hard stop the database and the files may not match: check them, a successful restore removes them.', esc(j.leftovers.join(', ')))}</div>`;  // 2.370.2 (#2779)
  h += j.items.length ? `<div class="members bklist">${j.items.map(x => `<div class="mrow bkrow" data-bkn="${esc(x.name)}"><span class="n"><b>${esc(aaWhen(x.created_at))}</b> · ${tr(BK_KIND[x.kind] || x.kind)} · ${fmtBytes(x.size)}${x.encrypted ? ` · ${ic('lock', 's')} ${tr('encrypted')}` : ''}${x.legacy ? ` · ${tr('old (SQLite), cannot be restored here')}` : ''}
      <small class="muted" style="display:block">${x.unreadable ? tr('unreadable') : `${trn('{0} task', '{0} tasks', x.counts.tasks || 0)}, ${trn('{0} file', '{0} files', x.attachment_files || 0)}${x.shared_files ? ` (${esc(trn('{0} shared', '{0} shared', x.shared_files))}${x.store_new_bytes ? ', ' + esc(tr('{0} newly stored', fmtBytes(x.store_new_bytes))) : ''})` : ''}, ${trn('{0} person', '{0} people', x.counts.users || 0)} · v${esc(x.app_version)}${x.missing_files ? ' · ' + esc(trn('{0} file missing', '{0} files missing', x.missing_files)) : ''}`}</small></span>
      <a class="iconbtn ms-phsr" href="/api/admin/backups/${encodeURIComponent(x.name)}/download" download="${esc(x.name)}" data-sudl title="${tr('Download')}">${ic('download', 's')}</a>
      <button class="iconbtn ms-phsr" data-bk="verify" title="${tr('Check')}">${ic('check', 's')}</button><button class="iconbtn ms-phsr" data-bk="restore" title="${tr('Restore')}">${ic('undo', 's')}</button><button class="iconbtn ms-phsr" data-bk="del" title="${tr('Delete')}">${ic('trash', 's')}</button>${/*html-ok*/ ms_dots('.ms-phsr', aaWhen(x.created_at)) /* 2.1151.0 C (#3835): one "…" on a phone */}</div>`).join('')}</div>` : `<div class="muted mhint">${tr('No backups yet.')}</div>`;
  h += `<div class="row"><label for="bk-file">${tr('Restore from a file')}</label>${fileBtn('bk-file', '.zip,.enc,application/zip')}${''/* lazy-ok: 2.149.0 F (#2519): settings dialog only */}</div>
    ${hint(tr('Larger files: copy them into the backup folder on the server instead, they then show up in the list.'))}`;
  box.innerHTML = h;
  box._body = bkBody(md);
  if (!$('#s-bko', md)?._j) bkoDraw(md);  // 2.143.0 B (#2152)
  if (j.running && !box._poll) box._poll = setTimeout(async () => { box._poll = null; if (md.isConnected) await bkDraw(md); }, 1500);
}
// 2.143.0 B (#2152): the off-site target (admin/offsite.py): S3, WebDAV or SFTP; credentials are only ever shown as "set"
const BKO_TYPES = [['', N_('None|target')], ['s3', N_('S3-compatible storage')], ['webdav', N_('WebDAV')], ['sftp', N_('SFTP')]];
const BKO_FIELDS = {s3: [['endpoint', N_('Endpoint'), 'url', 'https://s3.example.com'], ['region', N_('Region|storage'), 'text', 'us-east-1'], ['bucket', N_('Bucket'), 'text', ''], ['prefix', N_('Folder'), 'text', 'kalmido'],
  ['key', N_('Access key'), 'secret', 'key_set'], ['secret', N_('Secret key'), 'secret', 'secret_set']],
  webdav: [['url', N_('Address'), 'url', 'https://dav.example.com/backups'], ['user', N_('User name'), 'text', ''], ['password', N_('Password'), 'secret', 'password_set']],
  sftp: [['host', N_('Server'), 'text', 'backup.example.com'], ['port', N_('Port'), 'number', '22'], ['user', N_('User name'), 'text', ''], ['path', N_('Folder'), 'text', 'backups'],
    ['expect_fp', N_('Expected fingerprint'), 'text', 'SHA256:…']]};  // 2.550.0 (#4517): optional, as ssh-keygen -lf shows it
async function bkoDraw(md, j) {
  const box = $('#s-bko', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/admin/backups/offsite'); } catch { box.innerHTML = ''; return; } }
  box._j = j;
  if (j.hosted) { box.innerHTML = `<div class="shint">${tr('The off-site backup is set up by the operator.')}</div>`; return; }  // 2.552.0 (#4596): hosted, no form
  const t = j.type, x = j[t] || {}, hint = h => `<div class="shint">${h}</div>`;
  const field = ([k, label, kind, ph]) => `<div class="row"><label for="bko-${t}-${k}">${tr(label)}</label>${kind === 'secret'
    ? `<input type="password" id="bko-${t}-${k}" data-bkof="${k}" data-secret="1" autocomplete="new-password" placeholder="${x[ph] ? tr('set (unchanged)') : ''}">`
    : `<input type="${kind === 'number' ? 'number' : kind === 'url' ? 'url' : 'text'}" id="bko-${t}-${k}" data-bkof="${k}" ${kind === 'number' ? 'min="1" max="65535" class="aanum"' : ''} value="${esc(String(x[k] ?? ''))}" placeholder="${esc(ph)}" spellcheck="false" autocomplete="off">`}</div>`;
  let h = hint(tr('After every backup a copy goes to storage outside this server. Only encrypted backups are uploaded: the backup is encrypted with your passphrase before it leaves the server.'));
  if (!j.encrypt_ready) h += `<div class="shint cnote">${tr('Switch on “Encrypt backups” with a passphrase first.')}</div>`;
  h += `<div class="row"><label for="bko-type">${tr('Target')}</label><select id="bko-type">${BKO_TYPES.map(([k, n]) => `<option value="${k}" ${k === t ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>`;
  if (t) {
    h += (BKO_FIELDS[t] || []).map(field).join('');
    if (t === 's3') h += `<div class="featgrid"><label class="wide"><input type="checkbox" id="bko-s3-path" ${x.path_style ? 'checked' : ''}><span>${tr('Path-style addresses')}<small class="muted">${tr('Most self-hosted storage needs this; switch it off for addresses like bucket.s3.example.com.')}</small></span></label></div>`;
    if (t === 'sftp') {
      h += `<div class="row bkokey"><label for="bko-pub">${tr('Public key')}</label><input type="text" id="bko-pub" readonly value="${esc(x.public_key || '')}"><button type="button" class="iconbtn" data-bko="copy" title="${tr('Copy')}" aria-label="${tr('Copy')}">${ic('copy', 's')}</button></div>`
        + hint(tr('Add this key to the file ~/.ssh/authorized_keys of the user on the server. Kalmido signs in only with this key.'))
        + hint(x.fingerprint ? tr('Server fingerprint (saved): {0}', `<code>${esc(x.fingerprint)}</code>`) : tr('The first test that signs in saves the server’s fingerprint; after that only this server is accepted.'))
        + hint(tr('Optional: the fingerprint of the server’s host key from its administrator (ssh-keygen -lf). If set, a server with another key is refused and nothing is saved.'))  // 2.550.0 (#4517)
        + `<div class="row"><button type="button" class="btn sm" data-bko="newkey">${ic('key', 's')} ${tr('New key pair')}</button>${x.fingerprint ? `<button type="button" class="btn sm" data-bko="forget">${tr('Forget fingerprint')}</button>` : ''}</div>`;
    }
    h += `<div class="row"><label for="bko-keep">${tr('Keep')}</label><input type="number" class="aanum" id="bko-keep" min="1" max="365" value="${j.keep}"><span class="muted">${tr('newest backups on the target')}</span></div>
      <div class="featgrid"><label class="wide"><input type="checkbox" id="bko-on" ${j.on ? 'checked' : ''} ${j.encrypt_ready ? '' : 'disabled'}><span>${tr('Upload backups to the target')}</span></label></div>
      <div class="row"><button type="button" class="btn sm" data-bko="test">${ic('check', 's')} ${tr('Test connection')}</button><button type="button" class="btn sm" data-bko="upload" ${j.on && !j.running ? '' : 'disabled'}>${ic('upload', 's')} ${tr('Upload now')}</button><button type="button" class="btn sm" data-bko="remove">${ic('trash', 's')} ${tr('Remove target')}</button></div>`;
    const st = j.running ? tr('Uploading…') : j.last_ok ? tr('Last upload: {0}, {1}.', esc(aaWhen(j.last_ok)), fmtBytes(j.last_size)) : tr('No upload yet.');
    h += hint(st);
    if (j.last_error) h += `<div class="shint cnote bkoerr">${tr('The last upload failed ({0}): {1}', esc(aaWhen(j.last_error_at)), esc(j.last_error))}</div>`;
    // 2.538.0 (#4367): on, but nothing reached this target yet: the journal of deleted accounts waits for it
    if (j.upload_pending && !j.running) h += `<div class="shint cnote bkopend">${tr('The upload is on, but no backup has reached this target yet. Until one has, the journal of deleted accounts is not cleaned up: press “Upload now” or check the target.')}</div>`;
  }
  // 2.662.0 (#4587): backups at a removed / replaced target still count for the journal, until they expire (also without a target)
  if (j.former?.count) h += `<div class="shint bkoformer">${trh('Backups at a former off-site target still hold back the clean-up of the journal of deleted accounts: {0}, until {1} at the latest.', j.former.count, fmtDate(String(j.former.until).slice(0, 10)))}</div>`;
  box.innerHTML = h;
  if (j.running && !box._poll) box._poll = setTimeout(async () => { box._poll = null; if (md.isConnected) await bkoDraw(md); }, 2000);
}
const bkBody = md => $('#bk-on', md) ? {on: $('#bk-on', md).checked, time: $('#bk-time', md).value || '03:30', keep_daily: Math.max(1, +$('#bk-daily', md).value || 14), keep_weekly: Math.max(0, +$('#bk-weekly', md).value || 0), encrypt: $('#bk-enc', md).disabled ? undefined : $('#bk-enc', md).checked} : null;  // 2.152.0 B (#2172): required by the server = not sent
