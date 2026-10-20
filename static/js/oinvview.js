// @ts-check
/* Kalmido web client: Settings > Organisation > Invite by e-mail (2.115.0 B, #2062).
   An organisation's admin invites an address (role member / admin): a new account gets the invitation mail (or the link to
   copy), an address with an account is added as before. The open invitations of the organisation (accounts it invited that
   never signed in) with "Resend" and "Withdraw" (deletes that account). Inviting and withdrawing are one undo step each. */
const oinvRoleSel = (id, cur = 'member') => `<select id="${id}" aria-label="${esc(tr('Role'))}"><option value="member" ${cur !== 'admin' ? 'selected' : ''}>${tr('Member')}</option><option value="admin" ${cur === 'admin' ? 'selected' : ''}>${tr('Admin')}</option></select>`;
// called by wsPaneDraw (account.js): each organisation I administer gets the button + its open invitations
async function oinvDraw(box) {
  for (const det of $$('.wsorg[data-oid]', box)) {
    const oid = +det.dataset.oid, o = ((box._j || {}).orgs || []).find(x => x.id === oid);
    if (!o || o.role !== 'admin' || !(box._j || {}).manage) continue;
    let j; try { j = await api('GET', `/api/orgs/${oid}/invites`); } catch { continue; }
    if (!j.enabled) continue;
    $('.oinvbox', det)?.remove();
    const add = $('.wsadd', det);
    const html = `<div class="oinvbox"><div class="row"><button type="button" class="btn sm" data-oinv="new">${ic('send', 's')} ${tr('Invite by e-mail')}</button></div>
      ${j.invites.length ? `<div class="shint">${tr('Open invitations')}</div><div class="members">${j.invites.map(v => `<div class="mrow oinvrow" data-oinvu="${v.user_id}"><span class="avatar">${ic('mail', 's')}</span>
        <span class="n"><b>${esc(v.email || v.name)}</b><small class="muted">${esc([v.role === 'admin' ? tr('Admin') : tr('Member'), v.state === 'invited' ? tr('Invited') : tr('Invitation expired'), fmtWhen(v.created_at)].join(' · '))}</small></span>
        <button type="button" class="btn sm" data-oinv="resend">${tr('Resend')}</button><button type="button" class="btn sm" data-oinv="withdraw">${tr('Withdraw')}</button></div>`).join('')}</div>` : ''}</div>`;
    if (add) add.insertAdjacentHTML('afterend', html); else det.insertAdjacentHTML('beforeend', html);
  }
}
const oinvRedraw = () => { const md = $('#s-ws')?.closest('.modal') || document; if (typeof wsPaneDraw === 'function') wsPaneDraw(md); };
async function oinvSend(oid, email, role) {
  const r = await api('POST', `/api/orgs/${oid}/invites`, {email, role});
  if (r.invited && r.invitation) inviteResult(r.invitation, email);
  else toast(tr('If this address has an account, the person is now a member.'));
  return r;
}
function oinvDialog(oid) {
  /** @type {any} */
  const md = modal(`<h3>${ic('send', 's')} ${tr('Invite by e-mail')}</h3><form class="oinvform">
    <div class="row"><label for="oinv-mail">${tr('E-mail')}</label><input id="oinv-mail" type="email" required maxlength="200" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="send"></div>
    <div class="row"><label for="oinv-role">${tr('Role')}</label>${oinvRoleSel('oinv-role')}</div>
    <div class="shint">${tr('Without an account, a new one is created in this organisation and the person gets an e-mail to choose a password. With an account, the person is added.')}</div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" type="submit">${tr('Invite')}</button></div></form>`);
  md.addEventListener('click', e => { if (/** @type {any} */ (e.target).closest('[data-m="close"]')) md.remove(); });
  md.querySelector('form').addEventListener('submit', async e => {
    e.preventDefault();
    const email = $('#oinv-mail', md).value.trim(), role = $('#oinv-role', md).value, sb = md.querySelector('[type=submit]');
    if (!email) return;
    sb.disabled = true;
    try {
      const r = await oinvSend(oid, email, role); md.remove();
      if (r.invited) {  // one undo step: withdraw the new invitation again (redo = invite once more)
        let uid = r.user_id;
        histAdd({label: tr('Invite by e-mail'), sett: true,
          undo: async () => { await api('DELETE', `/api/orgs/${oid}/invites/${uid}`); oinvRedraw(); },
          redo: async () => { uid = (await api('POST', `/api/orgs/${oid}/invites`, {email, role})).user_id; oinvRedraw(); }});
      }
      await load(); render(); oinvRedraw();
    } catch { /* api() showed it */ } finally { sb.disabled = false; }
  });
  setTimeout(() => $('#oinv-mail', md)?.focus(), 50);
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-oinv]'); if (!b) return;
  const oid = +b.closest('[data-oid]')?.dataset.oid; if (!oid) return;
  if (b.dataset.oinv === 'new') { oinvDialog(oid); return; }
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
        undo: async () => { nu = (await api('POST', `/api/orgs/${oid}/invites`, {email: r.email, role: r.role})).user_id; oinvRedraw(); },
        redo: async () => { await api('DELETE', `/api/orgs/${oid}/invites/${nu}`); oinvRedraw(); }}));
      await load(); render();
    }
    oinvRedraw();
  } catch { /* api() showed it */ } finally { b.disabled = false; }
});
