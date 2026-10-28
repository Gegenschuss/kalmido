// ---- 2.42.0 (#828): Settings > Organisation > "Encryption" (admins of the organisation) and the instance switch
// org_encrypt (Settings > Administration > Organisation). The server encrypts the organisation's bank / tax data, purchase
// prices, framework contract rates and stored files with a key of the organisation (kalmido/core/orgcrypt.py); here: the
// state, and the recovery key (shown after the password, with a copy button and a plain warning). No switch for members.
// 2.46.0 (#1563): opt.title = the one heading (default "Encryption"), opt.title === '' = none (the section heading above says it)
function ocBoxHtml(o, opt = {}) {
  const t = opt.title ?? tr('Encryption');
  return `<div class="ocbox" data-ocorg="${o.id}">${t ? `<h5>${esc(t)}</h5>` : ''}
    <div class="ocst" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div></div>`;
}
function ocStateHtml(j) {
  if (!j.enabled) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Off: the server has no key (KALMIDO_SECRET_KEY). Bank and tax data, purchase prices and files are stored unencrypted, see SELF-HOSTING.md.'))}</div>`;
  if (j.key_ok === false) return `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The server key does not match this organisation’s key. Ask the server admin (SELF-HOSTING.md, recovery key).'))}</div>`;
  const when = x => x ? fmtDateNum(new Date(x)) : '';  // 2.368.0 B (#2982): one locale source
  // 2.46.0 (#1563): one text, so one "More information" link
  // 2.138.0 C (#1972): show (the same key again) or make a new one (the earlier one stops working); the full renewal of the
  // organisation's key runs on the server's command line (orgcrypt_cli rotate); a key of the earlier kind counts until then
  // 2.144.5 A (#2387, review F9): while it runs the search index is made again at the end, so the search may miss documents
  // live train fix: the earlier-kind and renewal notes (hints since 2.298.0, #3187) are part of the one text (#1563: one (i))
  return `<div class="shint">${esc(j.active ? tr('On: bank and tax data, purchase prices, framework contract rates and the files of the organisation’s projects and documents are stored encrypted with the organisation’s own key. Everyone who may see them sees them as before.')
      : tr('Paused by the server admin: new data is stored unencrypted, encrypted data stays readable.'))} ${esc(tr('The recovery key opens the organisation’s data if the server key is ever lost. Keep it offline, e.g. printed in a safe. Without the server key and without the recovery key the encrypted data is lost for good.'))}${!j.recovery && j.recovery_shown_at && !j.rotated_at ? ' ' + esc(tr('A recovery key of the earlier kind (13 groups without “R2-”) was shown before. It stays valid until the server admin renews the organisation’s key.')) : ''} ${esc(tr('The server admin can renew the organisation’s key completely on the command line, see SELF-HOSTING.md. All earlier recovery keys stop working on this server then; older exports and backups stay readable with the key of their time.'))}</div>
    ${j.rotating ? `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The organisation’s key is being renewed on the server. The recovery key can be shown again when that is finished.'))}</div><div class="mhint muted ocrotsearch">${esc(tr('Until the renewal is finished, the search may not find all of the organisation’s documents, files and pages.'))}</div>`
      : `<div class="row"><button type="button" class="btn sm" data-oc="show">${ic('key', 's')} ${tr('Show recovery key')}</button><button type="button" class="btn sm" data-oc="new">${ic('sync', 's')} ${tr('New recovery key')}</button>${j.recovery_shown_at ? `<span class="muted">${esc(tr('last shown {0}', when(j.recovery_shown_at)))}</span>` : ''}</div>`}
    ${j.recovery_stale && !j.rotating ? `<div class="shint keep">${ic('alert', 's')} ${esc(tr('The recovery key cannot be shown with the current server key. The one you kept stays valid; “New recovery key” makes a new one.'))}</div>` : ''}`;
}
// 2.138.0 C (#1972): News item "orgkey" (collab.js newsText): who showed / made new the recovery key, or the key was renewed
function ocNewsText(d, who, q) {
  const org = q(d.org || tr('Organisation'));
  if (d.action === 'rotated') return tr('The key of {0} was renewed on the server. Earlier recovery keys no longer work.', org);
  return d.action === 'new' ? tr('{0} made a new recovery key for {1}', who, org) : tr('{0} looked at the recovery key of {1}', who, org);
}
async function ocLoad(box) {
  const oid = +box.dataset.ocorg, st = $('.ocst', box);
  let j; try { j = oid ? await api('GET', `/api/orgs/${oid}/encryption`) : await rawFetch('GET', '/api/orgs/0/encryption'); } catch { if (!oid) box.hidden = true; else st.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  if (!oid && !j.has_key) { box.hidden = true; return; }  // 2.138.0 C (#1972): the personal office, once it holds encrypted data
  box._j = j;
  st.innerHTML = ocStateHtml(j) + (st.closest('.ocadm') ? '' : pm_cryptScopeHtml(j.scope));  // 2.46.1 (#1641): once per page
}
// 2.138.0 C (#1972): the step-up the server asks (status "step"): password, + code of the app / a recovery code (totp), + the
// passkey (passkey); without a password a fresh sign-in (fresh); signed in by the login proxy: only the server admin (proxy)
// 2.144.5 A (#2387): an SSO account (st.stepup 'oidc') signs in again at its login provider (prompt=login), unless this
// session did that in the last minutes (st.fresh); the provider sends it back to #rck-stepup/<org>/<show|new> (ocStepUpBack)
async function ocStepUp(oid, step, title, st = {}, isNew = false) {
  if (step === 'proxy') { toast(tr('You are signed in through the server’s login proxy. Ask the server admin for the recovery key (command line, SELF-HOSTING.md).')); return null; }
  if (step === 'fresh' && st.stepup === 'oidc' && !(isNew ? st.fresh_new : st.fresh)) {
    if (!await askConfirm(title, tr('Sign in again with your login provider to confirm. Kalmido then shows the key.'), {ok: tr('Sign in again')})) return null;
    // 2.144.5 A2 (#2387, review R1): only a step-up started here counts on the way back (ocStepUpBack), never a bare link
    try { sessionStorage.setItem('rck-stepup', `${+oid || 0}:${isNew ? 'new' : 'show'}`); } catch { /* storage off: the way back does nothing */ }
    location.href = `/api/auth/oidc/start?stepup=${isNew ? 'new' : 'show'}&org=${+oid || 0}`;
    return null;
  }
  if (step === 'fresh') return {};
  const p = await pwPrompt(title, {code: step === 'totp', text: esc(step === 'password' ? tr('Confirm with your password. Showing the key is noted in the office log.')
    : tr('Confirm with your password and your second factor. Showing the key is noted in the office log and the other admins are told.'))});
  if (!p) return null;
  const b = {password: p.password};
  if (step === 'totp') b.code = p.code;
  if (step === 'passkey') { try { b.credential = await pkGet(await api('POST', `/api/orgs/${oid}/encryption/recovery/passkey`)); } catch (e) { if (e?.name) toast(pkErr(e)); return null; } }
  return b;
}
async function ocShowRecovery(oid, st, isNew = false, confirmed = false) {
  const step = st?.step || (st?.password === false ? 'fresh' : 'password');
  if (isNew && !confirmed && !await askConfirm(tr('Make a new recovery key?'), tr('The current recovery key stops working at once. Keep the new one offline, e.g. printed in a safe.'), {ok: tr('New recovery key')})) return;
  const b = await ocStepUp(oid, step, isNew ? tr('New recovery key') : tr('Show recovery key'), st || {}, isNew);
  if (!b) return;
  let j; try { j = await api('POST', `/api/orgs/${oid}/encryption/recovery`, {...b, new: isNew}); } catch { return; /* api() showed it */ }
  const md = modal(`<h3>${tr('Recovery key')}</h3>
    <p class="shint keep">${ic('alert', 's')} ${esc(tr('Anyone with this key and a copy of the data can read the organisation’s encrypted data. Keep it offline and never send it by e-mail or chat. Without the server key and without this key the data is lost.'))}</p>
    ${j.new ? `<p class="mhint">${esc(tr('This is a new recovery key: earlier ones no longer work.'))}</p>` : ''}
    <div class="row"><code class="topic ocrk" id="oc-rk">${esc(j.recovery_key)}</code></div>
    <div class="foot"><button type="button" class="btn" data-m="copy">${ic('copy', 's')} ${tr('Copy')}</button><span class="spacer"></span><button type="button" class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'copy') toast(await clipCopy(j.recovery_key) ? tr('Copied') : tr('Copy failed, select the text by hand'));
    if (b.dataset.m === 'close') md.remove();
  });
}
function ocDraw(root) {
  root.querySelectorAll('.ocbox').forEach(ocLoad);
  if (root._ocWired) return;
  root._ocWired = true;
  root.addEventListener('click', async e => {
    const b = e.target.closest('[data-oc]'); if (!b) return;
    const box = b.closest('.ocbox'), oid = +box.dataset.ocorg;
    if (b.dataset.oc === 'show' || b.dataset.oc === 'new') { await ocShowRecovery(oid, box._j, b.dataset.oc === 'new'); ocLoad(box); }  // 2.138.0 C (#1972)
  });
}
// 2.144.5 A (#2387): back from the step-up sign-in at the login provider (oidc.py _oidc_stepup_done): show the key (the
// "new" was confirmed before leaving) or say why the sign-in did not count
const OC_STEPUP_ERR = {auth_time: N_('Your login provider did not say when you signed in, so it cannot confirm a fresh sign-in. Ask the server admin (the provider must send auth_time).'),
  old: N_('Your login provider did not ask for a new sign-in. Try again; if it keeps happening, ask the server admin.'),
  account: N_('That sign-in belongs to another account. Sign in again with your own account.'),
  denied: N_('The sign-in was cancelled.'),
  group: N_('Your account at the login provider is no longer allowed to use this app.')};  // 2.144.5 A2 (#2387, review R4)
function ocStepUpBack() {
  const h = location.hash, m = h.match(/^#rck-stepup\/(\d+)\/(show|new|su)$/), e = (h.match(/^#rck-stepup-error=([a-z_]+)$/) || [])[1];
  if (!m && !e) return;
  history.replaceState(null, '', '/');
  // 2.144.5 A2 (#2387, review R1): a link to #rck-stepup/… (comment, chat, task text) without an own step-up just before
  // does nothing; the pending one is used up either way
  let want = null; try { want = sessionStorage.getItem('rck-stepup'); sessionStorage.removeItem('rck-stepup'); } catch { /* no storage */ }
  if (!want || (m && want !== `${m[1]}:${m[2]}`)) return;
  let n = 0;
  const wait = () => {
    if (!(S.booted && S.me)) { if (++n < 120) setTimeout(wait, 500); return; }
    if (e) toast(tr(OC_STEPUP_ERR[e] || N_('Signing in again did not work. Try again.')));
    else if (m[2] === 'su') toast(tr('Confirmed. Now try the step again.'));  // 2.223.2 (#2871, review)
    else ocShowRecovery(+m[1], {step: 'fresh', fresh: true, fresh_new: m[2] === 'new'}, m[2] === 'new', true);
  };
  wait();
}
window.addEventListener('hashchange', ocStepUpBack);
ocStepUpBack();
// Administration > Organisation: the instance switch (with the boxes of the organisations I administer)
const ocAdminHtml = hint => `<h4 id="s-orgenc-h">${tr('Encryption of organisation data')}</h4>
  ${hint(tr('Bank and tax data, purchase prices, framework contract rates and the files of organisations are stored encrypted with a key per organisation, made from the server key KALMIDO_SECRET_KEY. Switched off, new data is stored unencrypted; encrypted data stays readable.'))}
  <div id="s-orgenc" aria-labelledby="s-orgenc-h"><div class="muted mhint">${tr('Loading…')}</div></div><div class="ocadm"></div>`;
async function ocAdminDraw(md) {
  const box = $('#s-orgenc', md); if (!box) return;
  let j, o; try { [j, o] = await Promise.all([api('GET', '/api/admin/orgcrypt'), api('GET', '/api/orgs')]); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box.innerHTML = j.enabled ? `<div class="featgrid"><label class="wide"><input type="checkbox" id="s-orgenc-on" ${j.org_encrypt ? 'checked' : ''}><span>${tr('Encrypt organisation data')}<small class="muted">${tr('Recommended. Existing data is encrypted in the background.')}</small></span></label></div>`
    : `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Off: the server has no key (KALMIDO_SECRET_KEY). Bank and tax data, purchase prices and files are stored unencrypted, see SELF-HOSTING.md.'))}</div>`;
  box.insertAdjacentHTML('beforeend', pm_cryptScopeHtml(j.scope));  // 2.46.1 (#1641): what is encrypted, what not
  const adm = $('.ocadm', box.parentNode);
  if (adm && j.enabled) { const mine = (o.orgs || []).filter(x => x.role === 'admin'); adm.innerHTML = mine.map(x => `<div class="ocorg">${ocBoxHtml(x, {title: mine.length > 1 ? x.name : ''})}</div>`).join(''); ocDraw(adm); }  // 2.46.0 (#1563): one heading (the organisation's name only with several)
  if (!box._ocWired) {
    box._ocWired = true;
    box.addEventListener('change', async e => {
      if (e.target.id !== 's-orgenc-on') return;
      try { await api('PUT', '/api/admin/orgcrypt', {org_encrypt: e.target.checked}); toast(tr('Saved')); } catch { e.target.checked = !e.target.checked; }
    });
  }
}

// ---- 2.46.0 (#1563): the boundary check in Administration > Organisation: unfolds to kind, object and person / agent; "Clean up"
// takes out the memberships of people (the server rule of the nightly run), agents must be moved to the right workspace by hand
const OA_TYPE = {list: N_('Project'), calendar: N_('Calendar'), book: N_('Address book'), agent: N_('Agent'), client: N_('Client'), event: N_('Appointment'), file: N_('File')};  // 2.59.0 (#1735): client: a contact person's address book link; 2.87.0 (#1983): event: an invitation; 2.148.1 H: file: a receipt
function oa_boundaryHtml(bd) {
  if (!bd.violations) return `<div class="mhint muted" id="a-orgs-bd">${esc(tr('Boundary check: nothing crosses the boundary between workspaces'))}</div>`;
  const head = trn('Boundary check: {0} membership crosses the boundary between workspaces', 'Boundary check: {0} memberships cross the boundary between workspaces', bd.violations);
  const det = bd.details || [];
  const rows = det.map(x => `<div class="mrow"><span class="n">${esc(tr(OA_TYPE[x.type] || x.type))}: <b>${esc(x.name || '#' + x.id)}</b> <span class="muted">${esc(x.user || '#' + x.user_id)}${x.agent ? ' ' + esc(tr('Agent')) : ''}</span></span></div>`).join('');
  const more = bd.violations > det.length ? `<div class="muted mhint">${esc(trn('and {0} more', 'and {0} more', bd.violations - det.length))}</div>` : '';
  const fix = det.some(x => x.fixable) ? `<div class="row"><button type="button" class="btn sm" data-oa="repair">${ic('check', 's')} ${tr('Clean up')}</button></div>` : '';
  const ag = det.some(x => x.agent) ? `<div class="shint keep">${esc(tr('Move the agent to the right workspace (Settings > Agents).'))}</div>` : '';
  return `<details class="sdet" id="a-orgs-bd"><summary class="mhint">${esc(head)}</summary><div class="members">${rows}</div>${more}${ag}${fix}</details>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-oa="repair"]'); if (!b) return;
  const md = b.closest('.modal') || document;
  if (!await askConfirm(tr('Clean up the boundary?'), tr('Takes people out of the projects, calendars and address books of an organisation they do not belong to. Agents stay as they are. This cannot be undone here.'), {ok: tr('Clean up'), danger: true})) return;
  let j; try { j = await api('POST', '/api/admin/orgs/boundary/repair', {}); } catch { return; /* api() said it */ }
  toast(j.removed ? trn('{0} membership removed', '{0} memberships removed', j.removed) : tr('Nothing to clean up'));
  if (typeof orgsDraw === 'function') orgsDraw(md);
});
// ---- 2.223.2 C (#2871): the same step-up before other sensitive steps (orgcrypt.py stepup_need): the off-site target of
// the backups and the export downloads. The server answers 403 + need (password | totp | passkey | fresh | proxy); suApi
// asks for it and sends the call once more with it (a confirmed step-up holds a few minutes on the server)
const SU_NEEDS = ['password', 'totp', 'passkey', 'fresh', 'proxy'];
async function suAsk(d, title) {
  if (d.need === 'proxy' || (d.need === 'fresh' && d.stepup !== 'oidc')) { toast(d.error || tr('Please sign in again, then try again.')); return null; }
  if (d.need === 'fresh') {  // a login-provider account: a sign-in there again (for the own office, oidc.py), then the step again
    if (!await askConfirm(title, tr('Sign in again with your login provider to confirm, then try again.'), {ok: tr('Sign in again')})) return null;
    try { sessionStorage.setItem('rck-stepup', '0:su'); } catch { /* storage off: no message on the way back */ }
    location.href = '/api/auth/oidc/start?stepup=su&org=0';  // 2.223.2 (#2871, review): own purpose (no office needed)
    return null;
  }
  const p = await pwPrompt(title, {code: d.need === 'totp', text: esc(d.need === 'password' ? tr('Confirm with your password') : tr('Confirm with your password and your second factor.'))});
  if (!p) return null;
  const b = {password: p.password};
  if (d.need === 'totp') b.code = p.code;
  if (d.need === 'passkey') { try { b.credential = await pkGet(await api('POST', '/api/stepup/passkey')); } catch (e) { if (e?.name) toast(pkErr(e)); return null; } }
  return b;
}
async function suApi(method, url, body, title) {
  const shout = e => { if (e instanceof Offline) toast(tr('Offline: only works again with a connection')); else if (e.message !== 'auth' && !e.shown) toast(e.message); throw e; };
  try { return await rawFetch(method, url, body); } catch (e) {
    if (!(e.status === 403 && SU_NEEDS.includes(e.data?.need))) shout(e);
    const b = await suAsk(e.data, title);
    if (!b) { e.shown = true; throw e; }
    try { return await rawFetch(method, url, {...(body || {}), ...b}); } catch (e2) { return shout(e2); }
  }
}
// a download link with data-sudl: POST (with the step-up) -> a one-time ticket, then the file with it
document.addEventListener('click', async e => {
  const a = e.target.closest?.('a[data-sudl]'); if (!a) return;
  e.preventDefault();
  const url = a.getAttribute('href');
  let j; try { j = await suApi('POST', url, {}, tr('Download')); } catch { return; }
  const x = document.createElement('a');
  x.href = `${url}?t=${encodeURIComponent(j.ticket)}`; x.download = ''; x.hidden = true;
  document.body.append(x); x.click(); x.remove();
}, true);  // capture: before the handlers of the dialog around it
