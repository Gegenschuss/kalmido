// @ts-check
/* Kalmido web client: Settings > Account > Delete account (2.553.0, #1413; server: kalmido/admin/selfdelete.py).
   The dialog names what happens (the same numbers as the admin's deletion dialog, ua8PurgeHtml in acctset.js), offers the
   export of everything first, asks per own project: hand it over to a member or delete it along (a shared one has no
   default: nothing shared goes without a choice), the retention step when records must be kept (rxAsk, orgexport.js), and
   the confirmation (password, the app code when one is set; without a password a fresh sign-in). Afterwards the account is
   locked for the waiting days and this browser is signed out; the mail and the sign-in offer "Cancel the deletion"
   (account.js lg_delScreen). Classic script sharing the global scope (load order: lazyload.js, module settings). */
const sdlHtml = () => S.me && !S.me.kid ? `<h4 id="s-sdl-h">${tr('Delete account')}</h4>
  <div class="shint">${tr('Deletes your account and your data permanently after a waiting time. You can export everything first.')}</div>
  <div class="row"><button type="button" class="btn sm danger" data-sdl="open">${ic('trash', 's')} ${tr('Delete account…')}</button></div>` : '';

// the choice of one project: its members who may take it over, or delete along (when allowed)
function sdlListRow(l, nodel) {
  const name = l.name != null ? esc(l.name) : esc(tr('A private project'));
  const shared = l.shared ? esc(l.members.length ? tr('shared with {0}', l.members.join(', ') + (l.shared > l.members.length ? ' ' + tr('+{0}', l.shared - l.members.length) : '')) : trn('shared with {0} person', 'shared with {0} people', l.shared)) : esc(tr('not shared'));
  const opts = (l.heirs || []).map((/** @type {any} */ p) => `<option value="to:${p.id}">${esc(tr('Hand over to {0}', p.name))}</option>`).join('');
  const del = nodel ? '' : `<option value="delete" ${l.shared ? '' : 'selected'}>${esc(tr('Delete along'))}</option>`;
  return `<div class="mrow sdlrow"><span class="n">${l.locked ? ic('lock', 's') + ' ' : ''}<b>${name}</b> <span class="muted">${l.org ? esc(l.org) + ' · ' : ''}${shared}</span></span>
    <select data-sdll="${l.id}" aria-label="${esc(tr('What happens to {0}', l.name || tr('A private project')))}">${l.shared || !del ? `<option value="">${esc(tr('Select'))}</option>` : ''}${opts}${del}</select></div>`;
}

async function sdlOpen(/** @type {any} */ sm) {
  /** @type {any} */ let j;
  try { j = await api('GET', '/api/account/delete'); } catch { return; }
  if (!j.can) { await askConfirm(tr('Delete account'), j.reason, {ok: tr('OK'), after: (/** @type {any} */ m) => { $('[data-cd="no"]', m).hidden = true; }}); return; }
  const rhost = !!j.retention?.hosted;
  const nodel = (/** @type {any} */ l) => l.foreign || (l.receipts && !rhost);
  const stuck = j.lists.filter((/** @type {any} */ l) => nodel(l) && !(l.heirs || []).length);
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('Delete your account?'))}</h3>
    <div class="shint keep warn">${ic('alert', 's')} ${esc(tr('Your account is locked at once and deleted permanently after {0} days. Until then you can cancel the deletion: with the link in the e-mail or by signing in with your password.', j.days))}</div>
    ${j.email ? '' : `<div class="shint keep">${esc(tr('Your account has no e-mail address: you get no e-mail with the cancel link. Cancel by signing in with your password.'))}</div>`}
    <div class="row"><button type="button" class="btn sm" data-sdl="export">${ic('download', 's')} ${tr('Export your data first')}</button></div>
    ${j.lists.length ? `<fieldset class="sdllists"><legend>${esc(trn('Your project', 'Your {0} projects', j.lists.length))}</legend>
      <div class="members">${j.lists.map((/** @type {any} */ l) => sdlListRow(l, nodel(l))).join('')}</div>
      ${j.lists.some((/** @type {any} */ l) => l.shared) ? `<div class="shint keep">${esc(tr('Projects you share stay usable for the others during the waiting time. Handed over, they stay; deleted along, the others lose them too.'))}</div>` : ''}
      ${j.lists.some((/** @type {any} */ l) => l.receipts && !rhost) ? `<div class="shint keep">${esc(tr('Projects with receipts cannot be deleted along (receipts are kept): hand them over instead.'))}</div>` : ''}
      ${stuck.length ? `<div class="shint keep warn">${ic('alert', 's')} ${esc(tr('Nobody can take over {0} yet: share it with someone first.', stuck.map((/** @type {any} */ l) => l.name || tr('A private project')).join(', ')))}</div>` : ''}
    </fieldset>` : ''}
    ${typeof ua8PurgeHtml === 'function' ? ua8PurgeHtml(j.purge) : ''}
    ${j.confirm === 'password' ? `<div class="row"><label for="sdl-pw">${tr('Password')}</label><input type="text" class="cfhid" hidden tabindex="-1" aria-hidden="true" autocomplete="username" value="${esc(j.username)}" readonly><input type="password" id="sdl-pw" autocomplete="current-password"></div>
      ${j.code ? `<div class="row"><label for="sdl-code">${tr('Code from the app')}</label><input id="sdl-code" inputmode="numeric" autocomplete="one-time-code" placeholder="${esc(tr('or a recovery code'))}"></div>` : ''}`
      : j.confirm === 'fresh' ? `<div class="shint keep">${esc(tr('To delete your account, please sign out and sign in again (at most {0} minutes ago).', j.fresh_minutes))}</div>`
        : `<div class="shint keep">${esc(tr('An admin can delete this account.'))}</div>`}
    <div class="aerr" role="alert" id="sdl-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn danger" data-m="go">${tr('Delete account')}</button></div>`));
  const choice = () => {
    /** @type {any} */ const out = {}; let ok = true;
    md.querySelectorAll('[data-sdll]').forEach((/** @type {any} */ s) => { const v = s.value; if (!v) ok = false; else out[s.dataset.sdll] = v === 'delete' ? {delete: true} : {to: +v.slice(3)}; });
    return ok ? out : null;
  };
  const sync = () => { /** @type {any} */ (md.querySelector('[data-m="go"]')).disabled = !choice() || stuck.length > 0 || j.confirm === 'admin' || (j.confirm === 'password' && !$('#sdl-pw', md).value); };
  md.addEventListener('change', sync); md.addEventListener('input', sync); sync();
  let rx = '';
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button[data-m], button[data-sdl]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.sdl === 'export') {  // Settings > Data > Move and export everything (move.js)
      md.remove();
      /** @type {any} */ (sm?.querySelector('[data-sec="data"]'))?.click();
      setTimeout(() => $('#s-umz-h', sm || document)?.scrollIntoView({block: 'start'}), 60);
      return;
    }
    const lists = choice(); if (!lists) return;
    const along = Object.values(lists).some((/** @type {any} */ x) => x.delete);
    if (!rx && j.retention?.needed && !j.retention.state || !rx && along && j.retention?.needed_along && !j.retention.state) {
      rx = typeof rxAsk === 'function' ? (await rxAsk(j.retention, S.me.display_name || S.me.username)) || '' : '';
      if (!rx) return;
    }
    b.disabled = true;
    const err = $('#sdl-err', md); err.textContent = '';
    try {
      const r = await rawFetch('POST', '/api/account/delete', {password: $('#sdl-pw', md)?.value || '', code: $('#sdl-code', md)?.value.trim() || '', lists, ...(rx ? {retention: rx} : {})});
      md.remove();
      await askConfirm(tr('Your account is locked'), tr('It will be deleted permanently on {0}. Until then you can cancel the deletion: with the link in the e-mail or by signing in with your password.', fmtDate(String(r.delete_at).slice(0, 10))), {ok: tr('OK'), after: (/** @type {any} */ m) => { $('[data-cd="no"]', m).hidden = true; }});
      location.replace('/');
    } catch (/** @type {any} */ x) {
      err.textContent = x?.message || tr('Not possible');
      if (x?.data?.code_needed) $('#sdl-code', md)?.focus();
      b.disabled = false;
    }
  });
}

document.addEventListener('click', (/** @type {any} */ e) => {
  const b = e.target.closest?.('[data-sdl="open"]'); if (!b) return;
  if (kd_pinNeed()) return kd_pinAsk(() => b.click());  // as the other account settings
  sdlOpen(b.closest('.modal'));
});
