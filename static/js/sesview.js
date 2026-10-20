// @ts-check
/* Kalmido web client: Settings > Account > Active sessions (2.115.0 B, #2062).
   The own browser sessions (device, browser and system read from the User-Agent, how the person signed in, since when, last
   activity), "this device" marked; end one (confirmation; the current one = log out) or all others. Ending a session is no
   undo step on purpose: a session that was ended cannot come back (a new login is the way). */
const SES_VIA = {password: N_('Password'), '2fa': N_('Password and second factor'), passkey: N_('Passkey'), oidc: N_('Single sign-on'),
  invite: N_('Invitation link'), link: N_('Sign-in link')};
const sesHtml = () => `<h4 id="s-ses-h">${tr('Active sessions')}</h4><div id="s-ses" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div>`;
const sesName = s => s.browser && s.system ? tr('{0} on {1}', s.browser, s.system) : s.browser || s.system || tr('Unknown device');
function sesIcon(s) { return ic(s.device === 'phone' || s.device === 'tablet' ? 'phone' : 'laptop', 's'); }
async function sesDraw(md) {
  const box = $('#s-ses', md); if (!box) return;
  let j; try { j = await api('GET', '/api/me/sessions'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  const day = x => x ? new Date(x).toLocaleDateString(I18N.code || 'en') : '';
  const others = j.sessions.filter(s => !s.current).length;
  box.innerHTML = (j.sessions.length ? `<div class="members seslist">${j.sessions.map(s => `<div class="mrow sesrow" data-sid="${esc(s.sid)}"><span class="avatar">${sesIcon(s)}</span>
      <span class="n"><b>${esc(sesName(s))}</b>${s.current ? ` <span class="tfastate on sescur">${tr('This device')}</span>` : ''}
      <small class="muted">${esc([s.current ? tr('active now') : tr('last active {0}', relTime(s.last_seen_at)), tr('signed in since {0}', day(s.created_at)), tr(SES_VIA[s.via] || SES_VIA.password)].join(' · '))}</small></span>
      <button class="btn sm" data-ses="end" aria-label="${esc(tr('Log out {0}', sesName(s)))}">${ic('logout', 's')} ${tr('Log out')}</button></div>`).join('')}</div>`
    : `<div class="muted mhint">${tr('No other sessions.')}</div>`)
    + (others ? `<div class="row"><button class="btn sm" data-ses="others">${ic('logout', 's')} ${tr('Log out everywhere else')}</button></div>` : '')
    + `<div class="shint">${tr('Every browser or app you are signed in with. Do you not recognise one? Log it out and change your password.')}</div>`;
}
document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-ses]'); if (!b) return;
  const md = b.closest('.modal') || document, box = $('#s-ses', md), j = box?._j; if (!j) return;
  if (kd_pinNeed()) return kd_pinAsk(() => b.click());  // a child with the parents' PIN: like the other account settings
  b.disabled = true;
  try {
    if (b.dataset.ses === 'end') {
      const s = j.sessions.find(x => x.sid === b.closest('[data-sid]').dataset.sid); if (!s) return;
      if (s.current) { logout(); return; }  // this device: the ordinary log out
      if (!await askConfirm(tr('Log out {0}?', sesName(s)), tr('This browser or app has to sign in again.'), {ok: tr('Log out'), danger: true})) return;
      await api('DELETE', '/api/me/sessions/' + encodeURIComponent(s.sid));
      toast(tr('Logged out'));
    } else {
      if (!await askConfirm(tr('Log out everywhere else?'), tr('Every other browser and app has to sign in again. This device stays signed in.'), {ok: tr('Log out'), danger: true})) return;
      const r = await api('POST', '/api/me/sessions/others');
      toast(trn('{0} session logged out', '{0} sessions logged out', r.ended));
    }
    await sesDraw(md);
  } catch { /* api() showed it */ } finally { b.disabled = false; }
});
