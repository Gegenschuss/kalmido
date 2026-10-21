// @ts-check
/* Kalmido web client: Settings > Organisation > Invite by e-mail (2.115.0 B, #2062).
   An organisation's admin invites an address (role member / admin): a new account gets the invitation mail (or the link to
   copy), an address with an account is added as before. The open invitations of the organisation (accounts it invited that
   never signed in) with "Resend" and "Withdraw" (deletes that account). Inviting and withdrawing are one undo step each. */
// 2.143.0 A (#2151): every organisation role (server: accounts/orgroles.py); hints = GET /api/orgs roles [{key, label, hint}]
const oinvRoleSel = (id, cur = 'member', hints = [], attrs = '') => `<select ${id ? `id="${id}" ` : ''}class="orgrolesel" ${attrs || `aria-label="${esc(tr('Role'))}"`}>${['member', 'admin', 'readonly', 'accounting', 'guest'].map(k =>
  `<option value="${k}" ${k === (cur || 'member') ? 'selected' : ''} title="${esc((hints.find(x => x.key === k) || {}).hint || '')}">${esc(oinvRoleSel.label(k))}</option>`).join('')}</select>`;
oinvRoleSel.label = r => ({admin: tr('Admin'), readonly: tr('Read-only'), accounting: tr('Accounting'), guest: tr('Guest')})[r] || tr('Member');
// the short explanation of each role (a closed details block next to the role pickers)
oinvRoleSel.help = (hints = []) => hints.length ? `<details class="orgrolehelp"><summary class="muted">${tr('What the roles mean')}</summary><ul class="shint keep">${hints.map(h => `<li><b>${esc(h.label)}</b>: ${esc(h.hint)}</li>`).join('')}</ul></details>` : '';
// called by wsPaneDraw (account.js): each organisation I administer gets the button + its open invitations
async function oinvDraw(box) {
  for (const det of $$('.wsorg[data-oid]', box)) {
    const oid = +det.dataset.oid, o = ((box._j || {}).orgs || []).find(x => x.id === oid);
    if (!o || o.role !== 'admin' || !(box._j || {}).manage) continue;
    let j; try { j = await api('GET', `/api/orgs/${oid}/invites`); } catch { continue; }
    if (!j.enabled) continue;
    $('.oinvbox', det)?.remove();
    const add = $('.wsadd', det);
    // 2.148.1 H (#2480): invitations of existing accounts are listed without an account id (no Resend / Withdraw)
    const html = `<div class="oinvbox"><div class="row"><button type="button" class="btn sm" data-oinv="new">${ic('send', 's')} ${tr('Invite by e-mail')}</button></div>
      ${j.invites.length ? `<div class="shint">${tr('Open invitations')}</div><div class="members">${j.invites.map(v => `<div class="mrow oinvrow" data-oinvu="${v.user_id || ''}"><span class="avatar">${ic('mail', 's')}</span>
        <span class="n"><b>${esc(v.email || v.name)}</b><small class="muted">${esc([oinvRoleSel.label(v.role), v.state === 'invited' ? tr('Invited') : tr('Invitation expired'), fmtWhen(v.created_at)].join(' · '))}</small></span>
        ${v.user_id ? `<button type="button" class="btn sm" data-oinv="resend">${tr('Resend')}</button><button type="button" class="btn sm" data-oinv="withdraw">${tr('Withdraw')}</button>` : ''}</div>`).join('')}</div>` : ''}</div>`;
    if (add) add.insertAdjacentHTML('afterend', html); else det.insertAdjacentHTML('beforeend', html);
  }
}
// 2.148.1 A (#2480): an organisation admin's answer carries no account id: the new invitation is found in the open ones
const oinvUid = (r, email) => r.user_id || ((r.invites || []).find(v => (v.email || '').toLowerCase() === String(email || '').toLowerCase()) || {}).user_id;
const oinvRedraw = () => { const md = $('#s-ws')?.closest('.modal') || document; if (typeof wsPaneDraw === 'function') wsPaneDraw(md); };
async function oinvSend(oid, email, role) {
  const r = await api('POST', `/api/orgs/${oid}/invites`, {email, role});
  if (r.invited && r.invitation) inviteResult(r.invitation, email);
  else if (r.notice) toast(r.notice);  // 2.148.1 A (#2486): the mail did not go (an organisation admin never gets the link)
  else toast(S.me?.is_admin ? tr('If this address has an account, the person is now a member.') : tr('Invitation sent. With an account, the person accepts it in their News.'));  // 2.148.1 A (#2480)
  return r;
}
function oinvDialog(oid, hints = []) {
  /** @type {any} */
  const md = modal(`<h3>${ic('send', 's')} ${tr('Invite by e-mail')}</h3><form class="oinvform">
    <div class="row"><label for="oinv-mail">${tr('E-mail')}</label><input id="oinv-mail" type="email" required maxlength="200" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="send"></div>
    <div class="row"><label for="oinv-role">${tr('Role')}</label>${oinvRoleSel('oinv-role', 'member', hints)}</div>
    <div class="shint oinvrolehint">${esc((hints.find(x => x.key === 'member') || {}).hint || '')}</div>
    <div class="shint">${S.me?.is_admin ? tr('Without an account, a new one is created in this organisation and the person gets an e-mail to choose a password. With an account, the person is added.')
      : tr('Without an account, a new one is created in this organisation and the person gets an e-mail to choose a password. With an account, the person gets an invitation to accept.')}</div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Invite')}</button></div></form>`);
  md.addEventListener('click', e => { if (/** @type {any} */ (e.target).closest('[data-m="close"]')) md.remove(); });
  $('#oinv-role', md).addEventListener('change', e => { $('.oinvrolehint', md).textContent = (hints.find(x => x.key === /** @type {any} */ (e.target).value) || {}).hint || ''; });  // 2.143.0 A (#2151)
  md.querySelector('form').addEventListener('submit', async e => {
    e.preventDefault();
    const email = $('#oinv-mail', md).value.trim(), role = $('#oinv-role', md).value, sb = md.querySelector('[type=submit]');
    if (!email) return;
    sb.disabled = true;
    try {
      const r = await oinvSend(oid, email, role); md.remove();
      let uid = oinvUid(r, email);
      if (uid) {  // one undo step: withdraw the new invitation again (redo = invite once more)
        histAdd({label: tr('Invite by e-mail'), sett: true,
          undo: async () => { await api('DELETE', `/api/orgs/${oid}/invites/${uid}`); oinvRedraw(); },
          redo: async () => { uid = oinvUid(await api('POST', `/api/orgs/${oid}/invites`, {email, role}), email); oinvRedraw(); }});
      }
      await load(); render(); oinvRedraw();
    } catch { /* api() showed it */ } finally { sb.disabled = false; }
  });
  setTimeout(() => $('#oinv-mail', md)?.focus(), 50);
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-oinv]'); if (!b) return;
  const oid = +b.closest('[data-oid]')?.dataset.oid; if (!oid) return;
  if (b.dataset.oinv === 'new') {  // 2.143.0 A (#2151): with the role explanations of GET /api/orgs (wsPaneDraw keeps it)
    const o = (($('#s-ws')?._j || {}).orgs || []).find(x => x.id === oid); oinvDialog(oid, o?.roles || []); return;
  }
  const row = b.closest('[data-oinvu]'), uid = +row?.dataset.oinvu; if (!uid) return;
  const who = $('b', row)?.textContent || '';
  b.disabled = true;
  try {
    if (b.dataset.oinv === 'resend') {
      const r = await api('POST', `/api/orgs/${oid}/invites/${uid}/resend`);
      inviteResult(r.invitation, who);
    } else {
      if (!await askConfirm(tr('Withdraw the invitation for {0}?', who), tr('The link stops working and the account, never used, is deleted.'), {ok: tr('Withdraw'), danger: true})) return;
      const r = await api('DELETE', `/api/orgs/${oid}/invites/${uid}`);
      let nu = uid;
      histToast(tr('Invitation withdrawn'), histAdd({label: tr('Invitation withdrawn'), sett: true,  // undo: the same address invited again
        undo: async () => { nu = oinvUid(await api('POST', `/api/orgs/${oid}/invites`, {email: r.email, role: r.role}), r.email); oinvRedraw(); },
        redo: async () => { await api('DELETE', `/api/orgs/${oid}/invites/${nu}`); oinvRedraw(); }}));
      await load(); render();
    }
    oinvRedraw();
  } catch { /* api() showed it */ } finally { b.disabled = false; }
});

// 2.148.1 A (#2480): an organisation's invitation of my existing account (a News item, GET /api/orgs joins): join or decline.
// "Later" keeps it open (it expires on the server after two weeks).
async function ojn_open(d) {
  const oid = +d.org_id; if (!oid) return;
  let dec = false;
  const yes = await askDialog({title: tr('Join the organisation {0}?', d.name || ''), ok: tr('Join'), cancel: tr('Later'),
    html: `<p>${esc(tr('Your role: {0}', oinvRoleSel.label(d.role)))}</p><p class="muted">${esc(tr('Its admins then see your name and can share lists with you. You can leave it at any time.'))}</p>
      <button type="button" class="linkbtn ojndecline" data-ojn="decline">${esc(tr('Decline the invitation'))}</button>`,
    after: md => $('[data-ojn="decline"]', md).addEventListener('click', () => { dec = true; $('[data-cd="no"]', md).click(); })});
  try {
    if (yes) { await api('POST', `/api/orgs/${oid}/join`); toast(tr('You joined {0}', d.name || '')); await load(); render(); }
    else if (dec) { await api('DELETE', `/api/orgs/${oid}/join`); toast(tr('Invitation declined')); }
    if (yes || dec) loadNews().then(() => { if (S.route.mod === 'news') renderView(); });
  } catch { /* api() showed it (e.g. the invitation expired) */ }
}
